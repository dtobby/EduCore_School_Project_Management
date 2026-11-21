import pytest
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from projects.models import Project

User = get_user_model()
pytestmark = pytest.mark.django_db

URL = "/api/admin/stats/"


def make_project(teacher, **kwargs):
    defaults = {
        "title": "Project",
        "deadline": timezone.now() + timedelta(days=10),
        "status": Project.Status.DRAFT,
    }
    defaults.update(kwargs)
    return Project.objects.create(created_by=teacher, **defaults)


# ── auth & permissions ────────────────────────────────────────────────────────

class TestAdminStatsAuth:
    def test_admin_can_access(self, client, admin_token):
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        assert resp.status_code == 200

    def test_teacher_returns_403(self, client, teacher_token):
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {teacher_token}")
        assert resp.status_code == 403

    def test_student_returns_403(self, client, student_token):
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {student_token}")
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, client):
        resp = client.get(URL)
        assert resp.status_code == 401


# ── response shape ────────────────────────────────────────────────────────────

class TestAdminStatsShape:
    def test_response_has_required_keys(self, client, admin_token):
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        data = resp.json()
        assert set(data.keys()) == {"users", "projects", "average_grade", "overdue_projects"}

    def test_all_user_roles_always_present(self, client, admin_token):
        # Only admin_user exists in this test — TEACHER and STUDENT should still appear as 0
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        assert set(resp.json()["users"].keys()) == {"ADMIN", "TEACHER", "STUDENT"}

    def test_all_project_statuses_always_present(self, client, admin_token):
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        assert set(resp.json()["projects"].keys()) == {"DRAFT", "IN_PROGRESS", "SUBMITTED", "GRADED"}


# ── user counts ───────────────────────────────────────────────────────────────

class TestAdminStatsUserCounts:
    def test_counts_users_by_role(self, client, admin_user, admin_token, teacher_user, student_user):
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        users = resp.json()["users"]
        assert users["ADMIN"] == 1
        assert users["TEACHER"] == 1
        assert users["STUDENT"] == 1

    def test_multiple_students_counted(self, client, admin_token, db):
        User.objects.create_user(username="s1", password="pass", role="STUDENT")
        User.objects.create_user(username="s2", password="pass", role="STUDENT")
        User.objects.create_user(username="s3", password="pass", role="STUDENT")

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        assert resp.json()["users"]["STUDENT"] == 3


# ── project counts ────────────────────────────────────────────────────────────

class TestAdminStatsProjectCounts:
    def test_counts_projects_by_status(self, client, admin_token, teacher_user):
        make_project(teacher_user, title="Draft 1", status=Project.Status.DRAFT)
        make_project(teacher_user, title="Draft 2", status=Project.Status.DRAFT)
        make_project(teacher_user, title="Active", status=Project.Status.IN_PROGRESS)

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        projects = resp.json()["projects"]
        assert projects["DRAFT"] == 2
        assert projects["IN_PROGRESS"] == 1
        assert projects["SUBMITTED"] == 0
        assert projects["GRADED"] == 0


# ── average grade ─────────────────────────────────────────────────────────────

class TestAdminStatsAverageGrade:
    def test_average_grade_of_graded_projects(self, client, admin_token, teacher_user):
        make_project(teacher_user, title="A", status=Project.Status.GRADED, grade=Decimal("80.00"))
        make_project(teacher_user, title="B", status=Project.Status.GRADED, grade=Decimal("60.00"))

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        assert float(resp.json()["average_grade"]) == pytest.approx(70.0)

    def test_average_grade_is_null_when_no_graded_projects(self, client, admin_token):
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        assert resp.json()["average_grade"] is None


# ── overdue count ─────────────────────────────────────────────────────────────

class TestAdminStatsOverdueCount:
    def test_counts_overdue_in_progress_projects(self, client, admin_token, teacher_user):
        # Overdue: IN_PROGRESS past deadline
        make_project(teacher_user, title="Overdue", status=Project.Status.IN_PROGRESS,
                     deadline=timezone.now() - timedelta(days=2))
        # Not overdue: IN_PROGRESS, future deadline
        make_project(teacher_user, title="On Time", status=Project.Status.IN_PROGRESS,
                     deadline=timezone.now() + timedelta(days=5))
        # Not counted: SUBMITTED past deadline (already submitted, not "overdue in progress")
        make_project(teacher_user, title="Late Submit", status=Project.Status.SUBMITTED,
                     deadline=timezone.now() - timedelta(days=1))

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        assert resp.json()["overdue_projects"] == 1

    def test_overdue_zero_when_no_in_progress(self, client, admin_token):
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        assert resp.json()["overdue_projects"] == 0
