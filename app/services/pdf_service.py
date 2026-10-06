"""
Shared PDF extraction. Pulls tables and text out of PDFs page by page,
using pdfplumber for text-based pages and local OCR for scanned pages.
The single source of truth all three converters build on.
"""

from functools import lru_cache
from io import BytesIO
import re
from threading import Lock

import numpy as np
import pdfplumber
import pypdfium2 as pdfium
from rapidocr import RapidOCR

_PDFIUM_LOCK = Lock()


def normalize_pdf_word(word: dict) -> dict:
    text = word["text"].replace("\uf0b7", "\u2022")
    fontname = re.sub(r"^[A-Z]{6}\+", "", word.get("fontname", ""))
    fontname = fontname.replace("LiberationSans", "Arial").replace("DejaVuSans", "Arial")
    lowered_fontname = fontname.casefold()
    return {
        **word,
        "text": text,
        "fontname": re.sub(r"-(bold|italic|oblique).*$", "", fontname, flags=re.IGNORECASE),
        "bold": "bold" in lowered_fontname,
        "italic": "italic" in lowered_fontname or "oblique" in lowered_fontname,
    }


def render_pdf_pages(pdf_path: str) -> list[bytes]:
    with _PDFIUM_LOCK:
        document = pdfium.PdfDocument(pdf_path)
        pages = []
        try:
            for page in document:
                try:
                    bitmap = page.render(scale=2)
                    try:
                        output = BytesIO()
                        bitmap.to_pil().convert("RGB").save(output, format="PNG")
                        pages.append(output.getvalue())
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        finally:
            document.close()
    return pages


def _extract_graphic_backgrounds(pdf_path: str) -> list[bytes]:
    with _PDFIUM_LOCK:
        document = pdfium.PdfDocument(pdf_path)
        backgrounds = []
        try:
            for page in document:
                objects = list(page.get_objects())
                try:
                    has_full_page_image = any(obj.type == 3 for obj in objects)
                    for obj in objects:
                        if obj.type == 1 or (has_full_page_image and obj.type == 3):
                            page.remove_obj(obj)

                    bitmap = page.render(scale=2)
                    image = bitmap.to_pil().convert("RGB")
                    bitmap.close()
                    output = BytesIO()
                    image.save(output, format="PNG")
                    backgrounds.append(output.getvalue())
                finally:
                    for obj in objects:
                        obj.close()
                    objects.clear()
                    page.close()
        finally:
            document.close()
    return backgrounds


def _group_positioned_words(words: list[dict], line_tolerance: float) -> list[list[dict]]:
    lines = []
    for word in sorted(words, key=lambda item: ((item["top"] + item["bottom"]) / 2, item["x0"])):
        center_y = (word["top"] + word["bottom"]) / 2
        line = next(
            (
                candidate
                for candidate in lines
                if abs(
                    center_y
                    - sum((item["top"] + item["bottom"]) / 2 for item in candidate)
                    / len(candidate)
                )
                <= line_tolerance
            ),
            None,
        )
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    return [sorted(line, key=lambda item: item["x0"]) for line in lines]


def _positioned_lines_from_pdf(page) -> list[dict]:
    words = page.extract_words(extra_attrs=["size", "fontname"])
    if not words:
        return []

    line_tolerance = max(
        2.0,
        float(np.median([word["bottom"] - word["top"] for word in words])) * 0.5,
    )
    lines = []
    for line_words in _group_positioned_words(words, line_tolerance):
        lines.append(
            {
                "x0": min(word["x0"] for word in line_words),
                "top": min(word["top"] for word in line_words),
                "bottom": max(word["bottom"] for word in line_words),
                "text": " ".join(word["text"] for word in line_words),
                "words": [
                    {
                        "text": word["text"],
                        "x0": word["x0"],
                        "x1": word["x1"],
                        "top": word["top"],
                        "bottom": word["bottom"],
                        "size": word.get("size", word["bottom"] - word["top"]),
                        "fontname": word.get("fontname", ""),
                    }
                    for word in line_words
                ],
            }
        )
    return sorted(lines, key=lambda line: line["top"])


@lru_cache(maxsize=1)
def _get_ocr_engine() -> RapidOCR:
    return RapidOCR()


def _extract_ocr_content(page) -> tuple[str, list[list[list[str]]], list[dict]]:
    with _PDFIUM_LOCK:
        image = page.to_image(resolution=400).original.convert("RGB")
    result = _get_ocr_engine()(np.asarray(image))
    if result is None or not result.txts or result.boxes is None or len(result.boxes) == 0:
        return "", [], []

    scale_x = image.width / page.width
    scale_y = image.height / page.height
    detections = []
    for text, box in zip(result.txts, result.boxes):
        text = text.strip()
        if not text:
            continue
        points = np.asarray(box)
        detections.append(
            {
                "text": text,
                "x0": float(points[:, 0].min()),
                "x1": float(points[:, 0].max()),
                "y0": float(points[:, 1].min()),
                "y1": float(points[:, 1].max()),
                "size": float(points[:, 1].max() - points[:, 1].min()) / scale_y,
            }
        )

    if not detections:
        return "", [], []

    line_tolerance = max(
        8.0,
        float(np.median([item["y1"] - item["y0"] for item in detections])) * 0.75,
    )
    for detection in detections:
        detection["top"] = detection["y0"]
        detection["bottom"] = detection["y1"]
    lines = _group_positioned_words(detections, line_tolerance)
    layout_lines = [
        {
            "x0": min(word["x0"] for word in line) / scale_x,
            "top": min(word["top"] for word in line) / scale_y,
            "bottom": max(word["bottom"] for word in line) / scale_y,
            "text": " ".join(word["text"] for word in line),
            "words": [
                {
                    "text": word["text"],
                    "x0": word["x0"] / scale_x,
                    "x1": word["x1"] / scale_x,
                    "top": word["top"] / scale_y,
                    "bottom": word["bottom"] / scale_y,
                    "size": word["size"],
                }
                for word in line
            ],
        }
        for line in lines
    ]
    layout_lines.sort(key=lambda line: line["top"])

    column_tolerance = line_tolerance
    columns = []
    for detection in sorted(detections, key=lambda item: item["x0"]):
        column = next(
            (
                candidate
                for candidate in columns
                if abs(detection["x0"] - candidate["x0"]) <= column_tolerance
            ),
            None,
        )
        if column is None:
            columns.append({"x0": detection["x0"], "items": [detection]})
        else:
            column["items"].append(detection)
            column["x0"] = sum(item["x0"] for item in column["items"]) / len(column["items"])

    columns.sort(key=lambda column: column["x0"])
    column_for_detection = {}
    recurring_columns = set()
    for column_index, column in enumerate(columns):
        rows_seen = set()
        for detection in column["items"]:
            for row_index, line in enumerate(lines):
                if detection in line:
                    rows_seen.add(row_index)
                    column_for_detection[id(detection)] = column_index
                    break
        if len(rows_seen) >= 2:
            recurring_columns.add(column_index)

    for line in lines:
        for detection in line:
            column_index = min(
                range(len(columns)),
                key=lambda index: abs(detection["x0"] - columns[index]["x0"]),
            )
            column_for_detection[id(detection)] = column_index

    rows = []
    for line in lines:
        ordered = sorted(line, key=lambda item: item["x0"])
        row = [""] * len(columns)
        for detection in ordered:
            column_index = column_for_detection[id(detection)]
            row[column_index] = " ".join(
                part for part in (row[column_index], detection["text"]) if part
            )
        rows.append((line, row))

    table_runs = []
    run = []
    for line_index, (_, row) in enumerate(rows):
        if sum(bool(row[index]) for index in recurring_columns) >= 2:
            run.append(line_index)
        else:
            if len(run) >= 2:
                table_runs.append(run)
            run = []
    if len(run) >= 2:
        table_runs.append(run)

    tables = []
    table_line_indices = set()
    for run in table_runs:
        columns_in_run = {
            index
            for index in recurring_columns
            if sum(bool(rows[row_index][1][index]) for row_index in run) >= 2
        }
        if len(columns_in_run) < 2:
            continue
        first_column = min(columns_in_run)
        last_column = max(columns_in_run)
        table = [
            [
                rows[row_index][1][index]
                for index in range(first_column, last_column + 1)
            ]
            for row_index in run
        ]
        tables.append(table)
        table_line_indices.update(run)

    text_lines = [
        " ".join(item["text"] for item in sorted(line, key=lambda item: item["x0"]))
        for line_index, (line, _) in enumerate(rows)
        if line_index not in table_line_indices
    ]
    return "\n".join(text_lines), tables, layout_lines


def extract_pdf_content(pdf_path: str, include_graphics: bool = False) -> list[dict]:
    """
    Returns a list of per-page dicts:
    [{"page_number": 1, "text": "...", "tables": [[[...]], ...]}, ...]
    """
    pages_data = []
    graphic_backgrounds = _extract_graphic_backgrounds(pdf_path) if include_graphics else []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables(
                table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"}
            )
            if not tables:
                tables = page.extract_tables(
                    table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"}
                )

            cleaned_tables = []
            for table in tables:
                cleaned = [
                    [(cell.strip() if isinstance(cell, str) else "") for cell in row]
                    for row in table
                ]
                if any(any(cell for cell in row) for row in cleaned):
                    cleaned_tables.append(cleaned)

            text = page.extract_text() or ""
            if not text.strip() and page.images:
                text, ocr_tables, layout_lines = _extract_ocr_content(page)
                cleaned_tables.extend(ocr_tables)
            else:
                layout_lines = _positioned_lines_from_pdf(page)

            if text.strip() and cleaned_tables:
                table_rows = {
                    "".join("".join(cell.casefold().split()) for cell in row if cell)
                    for table in cleaned_tables
                    for row in table
                }
                text = "\n".join(
                    line
                    for line in text.splitlines()
                    if "".join(line.casefold().split()) not in table_rows
                )

            page_data = {
                "page_number": i + 1,
                "width": page.width,
                "height": page.height,
                "text": text,
                "tables": cleaned_tables,
                "layout_lines": layout_lines,
            }
            if include_graphics:
                page_data["graphics_png"] = graphic_backgrounds[i]
            pages_data.append(page_data)

    return pages_data


def drop_blank_rows(table: list[list[str]]) -> list[list[str]]:
    """Removes rows that are 100% empty. Column positions are never
    touched, so a label and its value (wherever they happen to sit)
    stay exactly as aligned as they were — this only removes rows that
    carried zero information to begin with (common in PDFs built from
    dense bordered forms, where pdfplumber's grid detector inserts a
    blank spacer row between each labeled field block)."""
    return [row for row in table if any(cell and cell.strip() for cell in row)]


def clean_cell(text: str) -> str:
    """Strips garbage that bleeds in from rotated sidebar text in dense
    bordered forms (see build_content_blocks) — e.g. a stray single
    character like 'Y\\n2.SELLER'S NAME...' where the 'Y' leaked in from
    an adjacent rotated label. Whole cells that are almost entirely
    short fragmented lines (another rotated-text artifact) are dropped
    entirely rather than shown as noise."""
    if not text:
        return ""
    text = text.strip()
    if "\n" in text:
        lines = text.split("\n")
        avg_len = sum(len(line) for line in lines) / len(lines)
        if avg_len < 4 and len(lines) >= 3:
            return ""
        if len(lines[0]) <= 1 and len(lines) > 1:
            text = "\n".join(lines[1:]).strip()
    return text.strip()


def build_content_blocks(table: list[list[str]]) -> list[tuple]:
    """Splits a cleaned (blank-rows-already-dropped) table into blocks:

    - ("table", header_row, [data_row, ...]) — a real header + one or
      more data rows that share the EXACT same non-empty column
      positions. This is the only pattern reliable enough to treat as a
      genuine table (verified against real dense-form PDFs — matching
      column positions between consecutive rows is a strong, safe
      signal; guessing label/value pairs any other way was tested and
      produced confidently WRONG pairings, so that approach was
      deliberately dropped).
    - ("row", values, None) — anything that doesn't match that pattern.
      Shown as a plain list of whatever text was found on that line, in
      order, with NO guessed relationship between values — safer to
      show plainly than to risk mismatching data to the wrong label.
    """
    blocks = []
    i = 0
    n = len(table)
    while i < n:
        non_empty = [(c, clean_cell(v)) for c, v in enumerate(table[i])]
        non_empty = [(c, v) for c, v in non_empty if v]
        cols_i = tuple(c for c, _ in non_empty)

        matching_rows = []
        j = i + 1
        while j < n and len(cols_i) >= 2:
            non_empty_j = [(c, clean_cell(v)) for c, v in enumerate(table[j])]
            non_empty_j = [(c, v) for c, v in non_empty_j if v]
            if tuple(c for c, _ in non_empty_j) == cols_i:
                matching_rows.append([v for _, v in non_empty_j])
                j += 1
            else:
                break

        if matching_rows:
            blocks.append(("table", [v for _, v in non_empty], matching_rows))
            i = j
        else:
            vals = [v for _, v in non_empty]
            if vals:
                blocks.append(("row", vals, None))
            i += 1
    return blocks


def find_primary_table(pages_data: list[dict]) -> list[list[str]] | None:
    """Returns the first non-empty table found, in page order. PDFs with
    multiple tables only get this one offered for column mapping — a
    deliberate simplification (see the column-mapping feature's docs for
    why full multi-table merging isn't attempted)."""
    for page in pages_data:
        for table in page["tables"]:
            if table and len(table[0]) > 0:
                return table
    return None


def normalize_headers(header_row: list[str]) -> list[str]:
    """Fills in a placeholder name for any blank header cell, so every
    detected column has something displayable in the mapping UI."""
    result = []
    for i, cell in enumerate(header_row):
        name = (cell or "").strip()
        result.append(name if name else f"Column {i + 1}")
    return result


def detect_table_structure(pdf_path: str) -> dict:
    """Returns {"has_table": bool, "columns": [str, ...]} — the shape
    POST /api/pdf/analyze builds its response from."""
    pages_data = extract_pdf_content(pdf_path)
    table = find_primary_table(pages_data)

    if not table:
        return {"has_table": False, "columns": []}

    return {"has_table": True, "columns": normalize_headers(table[0])}
