"""
Regression tests for Step 11 — custom exception handler.

Rule: every 4xx response must have exactly: code, detail, fields.
Run: docker compose exec backend pytest accounts/tests/test_exceptions.py -v
"""
import pytest


ERROR_KEYS = {"code", "detail", "fields"}


def has_error_shape(data):
    """Helper — checks the response has exactly {code, detail, fields}."""
    return set(data.keys()) == ERROR_KEYS


# ── 401 unauthenticated ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestErrorFormat:
    def test_401_has_correct_shape(self, client):
        """No token → 401 with {code, detail, fields}."""
        res = client.get("/api/auth/me/")
        assert res.status_code == 401
        assert has_error_shape(res.data)
        assert res.data["code"] == "not_authenticated"
        assert res.data["fields"] == {}

    def test_401_wrong_password_has_correct_shape(self, client, teacher_user):
        """Wrong password → 401 with {code, detail, fields}."""
        res = client.post(
            "/api/auth/token/",
            {"username": "teacher1", "password": "wrong"},
            content_type="application/json",
        )
        assert res.status_code == 401
        assert has_error_shape(res.data)

    def test_detail_is_a_string(self, client):
        """detail must always be a string — not a list or dict."""
        res = client.get("/api/auth/me/")
        assert isinstance(res.data["detail"], str)

    def test_fields_is_always_present(self, client):
        """fields key must always exist, even when empty."""
        res = client.get("/api/auth/me/")
        assert "fields" in res.data


# ── 401 inactive user refresh ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestInactiveUserErrorFormat:
    def test_inactive_user_refresh_returns_correct_shape(self, client, teacher_user):
        """Deactivated user refresh → 401 with code=user_inactive."""
        # Get tokens while active
        tokens = client.post(
            "/api/auth/token/",
            {"username": "teacher1", "password": "teacher123"},
            content_type="application/json",
        ).data
        # Deactivate
        teacher_user.is_active = False
        teacher_user.save()
        # Refresh should fail
        res = client.post(
            "/api/auth/token/refresh/",
            {"refresh": tokens["refresh"]},
            content_type="application/json",
        )
        assert res.status_code == 401
        assert has_error_shape(res.data)
        assert res.data["code"] == "user_inactive"
