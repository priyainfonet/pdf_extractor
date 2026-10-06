import uuid
from tests.helpers import register_and_login, auth_headers, build_minimal_pdf


def unique_email():
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


def _register(client):
    access_token, _, user = register_and_login(client, unique_email())
    return access_token, user


# ------------------------------------------------------------------ upload
def test_upload_valid_pdf_succeeds(client):
    access_token, _ = _register(client)
    pdf_bytes = build_minimal_pdf()

    res = client.post(
        "/api/files/upload",
        files=[("files", ("test.pdf", pdf_bytes, "application/pdf"))],
        headers=auth_headers(access_token),
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert len(data) == 1
    assert data[0]["original_filename"] == "test.pdf"
    assert data[0]["file_size"] == len(pdf_bytes)
    assert data[0]["page_count"] == 1


def test_upload_multiple_files_succeeds(client):
    access_token, _ = _register(client)
    pdf_bytes = build_minimal_pdf()

    res = client.post(
        "/api/files/upload",
        files=[
            ("files", ("a.pdf", pdf_bytes, "application/pdf")),
            ("files", ("b.pdf", pdf_bytes, "application/pdf")),
        ],
        headers=auth_headers(access_token),
    )
    assert res.status_code == 201
    assert len(res.json()) == 2


def test_upload_without_auth_rejected(client):
    pdf_bytes = build_minimal_pdf()
    res = client.post("/api/files/upload", files=[("files", ("test.pdf", pdf_bytes, "application/pdf"))])
    assert res.status_code == 401


def test_upload_non_pdf_extension_rejected(client):
    access_token, _ = _register(client)
    res = client.post(
        "/api/files/upload",
        files=[("files", ("not-a-pdf.txt", b"just some text", "text/plain"))],
        headers=auth_headers(access_token),
    )
    assert res.status_code == 400


def test_upload_dangerous_extension_rejected(client):
    access_token, _ = _register(client)
    res = client.post(
        "/api/files/upload",
        files=[("files", ("malware.exe", b"MZ\x90\x00fake exe content", "application/octet-stream"))],
        headers=auth_headers(access_token),
    )
    assert res.status_code == 400


def test_upload_fake_pdf_extension_wrong_content_rejected(client):
    """A file named .pdf but whose actual bytes aren't a real PDF (magic
    byte check) — the browser's claimed filename/content-type is never
    trusted on its own."""
    access_token, _ = _register(client)
    res = client.post(
        "/api/files/upload",
        files=[("files", ("fake.pdf", b"this is not really a pdf file", "application/pdf"))],
        headers=auth_headers(access_token),
    )
    assert res.status_code == 400


def test_upload_empty_file_rejected(client):
    access_token, _ = _register(client)
    res = client.post(
        "/api/files/upload",
        files=[("files", ("empty.pdf", b"", "application/pdf"))],
        headers=auth_headers(access_token),
    )
    assert res.status_code == 400


def test_upload_exceeding_size_limit_rejected(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)  # anything at all now exceeds the limit

    access_token, _ = _register(client)
    pdf_bytes = build_minimal_pdf()
    res = client.post(
        "/api/files/upload",
        files=[("files", ("test.pdf", pdf_bytes, "application/pdf"))],
        headers=auth_headers(access_token),
    )
    assert res.status_code == 400


# -------------------------------------------------------------------- list
def test_list_files_returns_only_own_files(client):
    access_token_a, _ = _register(client)
    access_token_b, _ = _register(client)
    pdf_bytes = build_minimal_pdf()

    client.post(
        "/api/files/upload",
        files=[("files", ("a.pdf", pdf_bytes, "application/pdf"))],
        headers=auth_headers(access_token_a),
    )

    res_b = client.get("/api/files", headers=auth_headers(access_token_b))
    assert res_b.status_code == 200
    assert res_b.json() == []

    res_a = client.get("/api/files", headers=auth_headers(access_token_a))
    assert res_a.status_code == 200
    assert len(res_a.json()) == 1


# ------------------------------------------------------ ownership isolation
def test_user_cannot_access_another_users_file(client):
    access_token_a, _ = _register(client)
    access_token_b, _ = _register(client)
    pdf_bytes = build_minimal_pdf()

    upload_res = client.post(
        "/api/files/upload",
        files=[("files", ("a.pdf", pdf_bytes, "application/pdf"))],
        headers=auth_headers(access_token_a),
    )
    file_id = upload_res.json()[0]["id"]

    res = client.get(f"/api/files/{file_id}", headers=auth_headers(access_token_b))
    assert res.status_code == 404  # never a 403 — never reveals it exists


def test_user_cannot_delete_another_users_file(client):
    access_token_a, _ = _register(client)
    access_token_b, _ = _register(client)
    pdf_bytes = build_minimal_pdf()

    upload_res = client.post(
        "/api/files/upload",
        files=[("files", ("a.pdf", pdf_bytes, "application/pdf"))],
        headers=auth_headers(access_token_a),
    )
    file_id = upload_res.json()[0]["id"]

    res = client.delete(f"/api/files/{file_id}", headers=auth_headers(access_token_b))
    assert res.status_code == 404

    # And user A can still see it — it wasn't actually deleted.
    still_there = client.get(f"/api/files/{file_id}", headers=auth_headers(access_token_a))
    assert still_there.status_code == 200


def test_owner_can_delete_own_file(client):
    access_token, _ = _register(client)
    pdf_bytes = build_minimal_pdf()

    upload_res = client.post(
        "/api/files/upload",
        files=[("files", ("a.pdf", pdf_bytes, "application/pdf"))],
        headers=auth_headers(access_token),
    )
    file_id = upload_res.json()[0]["id"]

    delete_res = client.delete(f"/api/files/{file_id}", headers=auth_headers(access_token))
    assert delete_res.status_code == 204

    get_res = client.get(f"/api/files/{file_id}", headers=auth_headers(access_token))
    assert get_res.status_code == 404
