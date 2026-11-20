"""
Regression tests for Step 10 — JWT authentication.
Run: docker compose exec backend pytest accounts/tests/test_auth.py -v
"""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ── helpers ──────────────────────────────────────────────────────────────────

def login(client, username, password):
    return client.post(
        "/api/auth/token/",
        {"username": username, "password": password},
        content_type="application/json",
    )


def auth_get(client, url, token):
    return client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}")


# ── login tests ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLogin:
    def test_valid_credentials_return_tokens(self, client, teacher_user):
        """POST /api/auth/token/ with correct credentials returns access + refresh."""
        res = login(client, "teacher1", "teacher123")
        assert res.status_code == 200
        assert "access" in res.data
        assert "refresh" in res.data

    def test_wrong_password_returns_401(self, client, teacher_user):
        """Wrong password must return 401, not 500 or 200."""
        res = login(client, "teacher1", "wrongpassword")
        assert res.status_code == 401

    def test_unknown_user_returns_401(self, client):
        """Unknown username must return 401."""
        res = login(client, "nobody", "password")
        assert res.status_code == 401

    def test_inactive_user_cannot_login(self, client, teacher_user):
        """Deactivated user is rejected at login (FR-03)."""
        teacher_user.is_active = False
        teacher_user.save()
        res = login(client, "teacher1", "teacher123")
        assert res.status_code == 401


# ── /me/ tests ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestMeEndpoint:
    def test_returns_user_profile(self, client, teacher_user):
        """/me/ returns id, username, email, role for authenticated user."""
        tokens = login(client, "teacher1", "teacher123").data
        res = auth_get(client, "/api/auth/me/", tokens["access"])
        assert res.status_code == 200
        assert res.data["username"] == "teacher1"
        assert res.data["role"] == "TEACHER"
        assert "password" not in res.data

    def test_no_token_returns_401(self, client):
        """/me/ without a token returns 401."""
        res = client.get("/api/auth/me/")
        assert res.status_code == 401

    def test_role_is_correct_per_user_type(self, client, admin_user, student_user):
        """Each role gets back its own role string."""
        for username, password, expected_role in [
            ("admin", "admin123", "ADMIN"),
            ("student1", "student123", "STUDENT"),
        ]:
            tokens = login(client, username, password).data
            res = auth_get(client, "/api/auth/me/", tokens["access"])
            assert res.data["role"] == expected_role


# ── token refresh tests ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTokenRefresh:
    def test_valid_refresh_returns_new_access_token(self, client, teacher_user):
        """A valid refresh token returns a new access token."""
        tokens = login(client, "teacher1", "teacher123").data
        res = client.post(
            "/api/auth/token/refresh/",
            {"refresh": tokens["refresh"]},
            content_type="application/json",
        )
        assert res.status_code == 200
        assert "access" in res.data

    def test_inactive_user_cannot_refresh(self, client, teacher_user):
        """Deactivated user cannot get a new access token (FR-03). Core security rule."""
        # 1. Login while still active — get tokens
        tokens = login(client, "teacher1", "teacher123").data
        # 2. Admin deactivates the user
        teacher_user.is_active = False
        teacher_user.save()
        # 3. Try to refresh — must be rejected
        res = client.post(
            "/api/auth/token/refresh/",
            {"refresh": tokens["refresh"]},
            content_type="application/json",
        )
        assert res.status_code == 401
