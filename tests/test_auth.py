import uuid
from tests.helpers import register_and_login, auth_headers


def unique_email():
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


# ---------------------------------------------------------------- register
def test_register_success(client):
    email = unique_email()
    access_token, refresh_token, user = register_and_login(client, email)
    assert user["email"] == email
    assert user["first_name"] == "Test"
    assert access_token and refresh_token


def test_register_duplicate_email_rejected(client):
    email = unique_email()
    register_and_login(client, email)

    res = client.post(
        "/api/auth/register",
        json={
            "first_name": "Another",
            "last_name": "Person",
            "email": email,
            "password": "TestPass1234",
            "confirm_password": "TestPass1234",
        },
    )
    assert res.status_code == 409


def test_register_password_too_short_rejected(client):
    res = client.post(
        "/api/auth/register",
        json={
            "first_name": "Test",
            "last_name": "User",
            "email": unique_email(),
            "password": "short",
            "confirm_password": "short",
        },
    )
    assert res.status_code == 422


def test_register_password_mismatch_rejected(client):
    res = client.post(
        "/api/auth/register",
        json={
            "first_name": "Test",
            "last_name": "User",
            "email": unique_email(),
            "password": "TestPass1234",
            "confirm_password": "DifferentPass1234",
        },
    )
    assert res.status_code == 422


def test_register_invalid_email_rejected(client):
    res = client.post(
        "/api/auth/register",
        json={
            "first_name": "Test",
            "last_name": "User",
            "email": "not-an-email",
            "password": "TestPass1234",
            "confirm_password": "TestPass1234",
        },
    )
    assert res.status_code == 422


# ------------------------------------------------------------------ login
def test_login_success(client):
    email = unique_email()
    register_and_login(client, email, password="CorrectPass1234")

    res = client.post("/api/auth/login", json={"email": email, "password": "CorrectPass1234"})
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_login_wrong_password_rejected(client):
    email = unique_email()
    register_and_login(client, email, password="CorrectPass1234")

    res = client.post("/api/auth/login", json={"email": email, "password": "WrongPassword"})
    assert res.status_code == 401


def test_login_nonexistent_email_rejected(client):
    res = client.post("/api/auth/login", json={"email": unique_email(), "password": "whatever123"})
    assert res.status_code == 401


# ---------------------------------------------------------- protected routes
def test_protected_route_without_token_rejected(client):
    res = client.get("/api/users/me")
    assert res.status_code == 401


def test_protected_route_with_invalid_token_rejected(client):
    res = client.get("/api/users/me", headers=auth_headers("not-a-real-token"))
    assert res.status_code == 401


def test_protected_route_with_valid_token_succeeds(client):
    access_token, _, user = register_and_login(client, unique_email())
    res = client.get("/api/users/me", headers=auth_headers(access_token))
    assert res.status_code == 200
    assert res.json()["email"] == user["email"]


# ----------------------------------------------------------- refresh rotation
def test_refresh_rotation(client):
    _, refresh_token, _ = register_and_login(client, unique_email())

    first = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert first.status_code == 200

    # Reusing the same (now rotated-out) refresh token must fail.
    second = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert second.status_code == 401


def test_refresh_with_garbage_token_rejected(client):
    res = client.post("/api/auth/refresh", json={"refresh_token": "garbage"})
    assert res.status_code == 401


# ------------------------------------------------------------------- logout
def test_logout_revokes_refresh_token(client):
    access_token, refresh_token, _ = register_and_login(client, unique_email())

    logout_res = client.post(
        "/api/auth/logout",
        json={"refresh_token": refresh_token},
        headers=auth_headers(access_token),
    )
    assert logout_res.status_code == 204

    refresh_res = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_res.status_code == 401


def test_logout_requires_auth(client):
    res = client.post("/api/auth/logout", json={})
    assert res.status_code == 401


# --------------------------------------------------------------- rate limit
def test_login_rate_limited_after_repeated_failures(client):
    email = unique_email()
    register_and_login(client, email, password="CorrectPass1234")

    last_status = None
    for _ in range(11):
        res = client.post("/api/auth/login", json={"email": email, "password": "WrongPassword"})
        last_status = res.status_code

    assert last_status == 429


# ----------------------------------------------------------- password reset
def test_password_reset_flow(client, db_session):
    from app.services import auth_service
    from app.models.user import User

    email = unique_email()
    register_and_login(client, email, password="OldPass1234")

    user = db_session.query(User).filter(User.email == email).first()
    reset_token = auth_service.create_password_reset_token(db_session, user)

    reset_res = client.post(
        "/api/auth/reset-password", json={"token": reset_token, "new_password": "NewPass5678"}
    )
    assert reset_res.status_code == 200

    login_old = client.post("/api/auth/login", json={"email": email, "password": "OldPass1234"})
    assert login_old.status_code == 401

    login_new = client.post("/api/auth/login", json={"email": email, "password": "NewPass5678"})
    assert login_new.status_code == 200


def test_password_reset_token_is_single_use(client, db_session):
    from app.services import auth_service
    from app.models.user import User

    email = unique_email()
    register_and_login(client, email, password="OldPass1234")

    user = db_session.query(User).filter(User.email == email).first()
    reset_token = auth_service.create_password_reset_token(db_session, user)

    first = client.post("/api/auth/reset-password", json={"token": reset_token, "new_password": "NewPass5678"})
    assert first.status_code == 200

    second = client.post("/api/auth/reset-password", json={"token": reset_token, "new_password": "AnotherPass999"})
    assert second.status_code == 400


def test_forgot_password_always_returns_generic_response(client):
    # Same response whether or not the email is registered — never
    # reveal which emails exist in the system.
    res_unknown = client.post("/api/auth/forgot-password", json={"email": unique_email()})
    assert res_unknown.status_code == 202

    email = unique_email()
    register_and_login(client, email)
    res_known = client.post("/api/auth/forgot-password", json={"email": email})
    assert res_known.status_code == 202
    assert res_unknown.json() == res_known.json()
