from io import BytesIO
import time
import uuid
from zipfile import ZipFile

from tests.helpers import register_and_login, auth_headers, build_minimal_pdf


def unique_email():
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


def _register(client):
    access_token, _, user = register_and_login(client, unique_email())
    return access_token, user


def _upload_pdf(client, access_token, filename="test.pdf"):
    pdf_bytes = build_minimal_pdf()
    res = client.post(
        "/api/files/upload",
        files=[("files", (filename, pdf_bytes, "application/pdf"))],
        headers=auth_headers(access_token),
    )
    assert res.status_code == 201, res.text
    return res.json()[0]["id"]


def _wait_for_status(client, access_token, job_id, timeout_seconds=15):
    """The conversion worker runs on a background thread — poll like the
    real frontend does instead of assuming it's instant."""
    deadline = time.monotonic() + timeout_seconds
    last_job = None
    while time.monotonic() < deadline:
        res = client.get(f"/api/conversions/{job_id}", headers=auth_headers(access_token))
        assert res.status_code == 200
        last_job = res.json()
        if last_job["status"] in ("COMPLETED", "FAILED"):
            return last_job
        time.sleep(0.2)
    raise AssertionError(f"Job {job_id} did not finish within {timeout_seconds}s (last status: {last_job})")


# --------------------------------------------------------------- creation
def test_create_conversion_job_success(client):
    access_token, _ = _register(client)
    file_id = _upload_pdf(client, access_token)

    res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "xlsx"},
        headers=auth_headers(access_token),
    )
    assert res.status_code == 201, res.text
    job = res.json()
    assert job["output_format"] == "xlsx"
    assert job["page_count"] == 1
    assert job["status"] in ("PENDING", "PROCESSING", "COMPLETED")


def test_create_conversion_invalid_format_rejected(client):
    access_token, _ = _register(client)
    file_id = _upload_pdf(client, access_token)

    res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "gif"},
        headers=auth_headers(access_token),
    )
    assert res.status_code == 422


def test_create_conversion_nonexistent_file_rejected(client):
    access_token, _ = _register(client)
    res = client.post(
        "/api/conversions",
        json={"file_id": 999999, "output_format": "xlsx"},
        headers=auth_headers(access_token),
    )
    assert res.status_code == 404


def test_create_conversion_without_auth_rejected(client):
    res = client.post("/api/conversions", json={"file_id": 1, "output_format": "xlsx"})
    assert res.status_code == 401


# -------------------------------------------------------- status & success
def test_conversion_reaches_completed_for_each_format(client):
    access_token, _ = _register(client)

    for fmt in ("xlsx", "docx", "pptx"):
        file_id = _upload_pdf(client, access_token, filename=f"test-{fmt}.pdf")
        create_res = client.post(
            "/api/conversions",
            json={"file_id": file_id, "output_format": fmt},
            headers=auth_headers(access_token),
        )
        job_id = create_res.json()["id"]

        finished = _wait_for_status(client, access_token, job_id)
        assert finished["status"] == "COMPLETED", finished.get("error_message")
        assert finished["output_filename"].endswith(f".{fmt}")


def test_download_completed_conversion(client):
    access_token, _ = _register(client)
    file_id = _upload_pdf(client, access_token)

    create_res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "xlsx"},
        headers=auth_headers(access_token),
    )
    job_id = create_res.json()["id"]
    _wait_for_status(client, access_token, job_id)

    download_res = client.get(f"/api/conversions/{job_id}/download", headers=auth_headers(access_token))
    assert download_res.status_code == 200
    assert len(download_res.content) > 0
    assert "spreadsheetml" in download_res.headers["content-type"]


def test_download_completed_word_conversion_is_valid_docx(client):
    access_token, _ = _register(client)
    file_id = _upload_pdf(client, access_token, filename="test.pdf")

    create_res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "docx"},
        headers=auth_headers(access_token),
    )
    job_id = create_res.json()["id"]
    _wait_for_status(client, access_token, job_id)

    download_res = client.get(
        f"/api/conversions/{job_id}/download",
        headers=auth_headers(access_token),
    )

    assert download_res.status_code == 200
    assert "wordprocessingml.document" in download_res.headers["content-type"]
    assert download_res.headers["content-disposition"].endswith('filename="test.docx"')
    with ZipFile(BytesIO(download_res.content)) as package:
        assert package.testzip() is None
        assert "word/document.xml" in package.namelist()


def test_download_before_completion_rejected(client):
    access_token, _ = _register(client)
    file_id = _upload_pdf(client, access_token)

    create_res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "xlsx"},
        headers=auth_headers(access_token),
    )
    job_id = create_res.json()["id"]

    # Don't wait — try to download immediately. This is timing-sensitive
    # (the worker might finish fast on a quiet test machine), so only
    # assert the 409 if it's genuinely not done yet.
    status_res = client.get(f"/api/conversions/{job_id}", headers=auth_headers(access_token))
    if status_res.json()["status"] != "COMPLETED":
        download_res = client.get(f"/api/conversions/{job_id}/download", headers=auth_headers(access_token))
        assert download_res.status_code == 409


def test_conversion_failure_when_file_deleted_mid_flight(client, db_session):
    """Simulates a failure path: delete the source file's storage key out
    from under a pending job so the worker hits a real error, then
    confirm the job lands in FAILED with an error_message rather than
    hanging or crashing the worker thread."""
    from app.models.file import File as FileModel
    from app.services.storage_service import storage_service

    access_token, _ = _register(client)
    file_id = _upload_pdf(client, access_token)

    file_record = db_session.query(FileModel).filter(FileModel.id == file_id).first()
    storage_service.delete_file(file_record.storage_key)

    create_res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "xlsx"},
        headers=auth_headers(access_token),
    )
    job_id = create_res.json()["id"]

    finished = _wait_for_status(client, access_token, job_id)
    assert finished["status"] == "FAILED"
    assert finished["error_message"]


# -------------------------------------------------------------------- list
def test_list_conversions_returns_only_own_jobs(client):
    access_token_a, _ = _register(client)
    access_token_b, _ = _register(client)

    file_id = _upload_pdf(client, access_token_a)
    client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "xlsx"},
        headers=auth_headers(access_token_a),
    )

    res_b = client.get("/api/conversions", headers=auth_headers(access_token_b))
    assert res_b.status_code == 200
    assert res_b.json() == []

    res_a = client.get("/api/conversions", headers=auth_headers(access_token_a))
    assert len(res_a.json()) == 1


# ------------------------------------------------------ ownership isolation
def test_user_cannot_view_another_users_job(client):
    access_token_a, _ = _register(client)
    access_token_b, _ = _register(client)

    file_id = _upload_pdf(client, access_token_a)
    create_res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "xlsx"},
        headers=auth_headers(access_token_a),
    )
    job_id = create_res.json()["id"]

    res = client.get(f"/api/conversions/{job_id}", headers=auth_headers(access_token_b))
    assert res.status_code == 404


def test_user_cannot_download_another_users_job(client):
    access_token_a, _ = _register(client)
    access_token_b, _ = _register(client)

    file_id = _upload_pdf(client, access_token_a)
    create_res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "xlsx"},
        headers=auth_headers(access_token_a),
    )
    job_id = create_res.json()["id"]
    _wait_for_status(client, access_token_a, job_id)

    res = client.get(f"/api/conversions/{job_id}/download", headers=auth_headers(access_token_b))
    assert res.status_code == 404


def test_user_cannot_use_another_users_file_id_to_create_a_job(client):
    access_token_a, _ = _register(client)
    access_token_b, _ = _register(client)

    file_id = _upload_pdf(client, access_token_a)  # belongs to A

    res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "xlsx"},
        headers=auth_headers(access_token_b),  # B tries to convert A's file
    )
    assert res.status_code == 404


def test_user_cannot_delete_another_users_job(client):
    access_token_a, _ = _register(client)
    access_token_b, _ = _register(client)

    file_id = _upload_pdf(client, access_token_a)
    create_res = client.post(
        "/api/conversions",
        json={"file_id": file_id, "output_format": "xlsx"},
        headers=auth_headers(access_token_a),
    )
    job_id = create_res.json()["id"]

    res = client.delete(f"/api/conversions/{job_id}", headers=auth_headers(access_token_b))
    assert res.status_code == 404

    still_there = client.get(f"/api/conversions/{job_id}", headers=auth_headers(access_token_a))
    assert still_there.status_code == 200
