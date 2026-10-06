"""
Test helpers. The PDF builder constructs a genuinely valid minimal
single-page PDF with correctly computed xref byte offsets (not a
hardcoded/guessed template) — pdfplumber needs a structurally valid PDF
to open, and getting the offsets right matters for parsers that don't
fall back to recovery mode.
"""


def build_minimal_pdf() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << >> >>",
    ]

    header = b"%PDF-1.4\n"
    body_parts = []
    offsets = [0]  # object 0 is always free, offset unused
    pos = len(header)

    for i, obj_body in enumerate(objects, start=1):
        obj_bytes = f"{i} 0 obj\n".encode() + obj_body + b"\nendobj\n"
        offsets.append(pos)
        body_parts.append(obj_bytes)
        pos += len(obj_bytes)

    body = b"".join(body_parts)
    xref_offset = len(header) + len(body)

    xref_lines = [b"xref\n", f"0 {len(objects) + 1}\n".encode(), b"0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref_lines.append(f"{off:010d} 00000 n \n".encode())
    xref = b"".join(xref_lines)

    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
        + f"startxref\n{xref_offset}\n".encode()
        + b"%%EOF"
    )

    return header + body + xref + trailer


def register_and_login(client, email: str, password: str = "TestPass1234", first_name="Test", last_name="User"):
    """Registers a new user and returns (access_token, refresh_token, user_dict)."""
    res = client.post(
        "/api/auth/register",
        json={
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    return data["access_token"], data["refresh_token"], data["user"]


def auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}
