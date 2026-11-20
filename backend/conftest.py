import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin", password="admin123", role="ADMIN"
    )


@pytest.fixture
def teacher_user(db):
    return User.objects.create_user(
        username="teacher1", password="teacher123", role="TEACHER"
    )


@pytest.fixture
def student_user(db):
    return User.objects.create_user(
        username="student1", password="student123", role="STUDENT"
    )


@pytest.fixture
def teacher_token(client, teacher_user):
    response = client.post(
        "/api/auth/token/",
        {"username": "teacher1", "password": "teacher123"},
        content_type="application/json",
    )
    return response.data["access"]


@pytest.fixture
def student_token(client, student_user):
    response = client.post(
        "/api/auth/token/",
        {"username": "student1", "password": "student123"},
        content_type="application/json",
    )
    return response.data["access"]


@pytest.fixture
def admin_token(client, admin_user):
    response = client.post(
        "/api/auth/token/",
        {"username": "admin", "password": "admin123"},
        content_type="application/json",
    )
    return response.data["access"]
