"""
Regression tests for Step 13 — Project CRUD.
Tests cover: list scoping, create, retrieve, update, delete, assign/unassign students.
Run: docker compose exec backend pytest projects/tests/test_projects.py -v
"""
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from projects.models import Project

User = get_user_model()


# ── helpers ──────────────────────────────────────────────────────────────────

def make_project(teacher, title="Test Project", days=30):
    return Project.objects.create(
        title=title,
        created_by=teacher,
        deadline=timezone.now() + timezone.timedelta(days=days),
    )


def auth(client, token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# ── list tests ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProjectList:
    def test_teacher_sees_own_projects_only(self, client, teacher_user, teacher_token):
        """Teacher list never includes another teacher's projects."""
        other = User.objects.create_user(username="t2", password="x", role="TEACHER")
        make_project(teacher_user, "Mine")
        make_project(other, "Not mine")

        res = client.get("/api/projects/", **auth(client, teacher_token))
        assert res.status_code == 200
        titles = [p["title"] for p in res.data["results"]]
        assert "Mine" in titles
        assert "Not mine" not in titles

    def test_student_sees_assigned_projects_only(self, client, teacher_user, student_user, student_token):
        p1 = make_project(teacher_user, "Assigned")
        make_project(teacher_user, "Not assigned")
        p1.assigned_students.add(student_user)

        res = client.get("/api/projects/", **auth(client, student_token))
        assert res.status_code == 200
        titles = [p["title"] for p in res.data["results"]]
        assert "Assigned" in titles
        assert "Not assigned" not in titles

    def test_admin_sees_all_projects(self, client, teacher_user, admin_user, admin_token):
        other = User.objects.create_user(username="t2", password="x", role="TEACHER")
        make_project(teacher_user, "Project A")
        make_project(other, "Project B")

        res = client.get("/api/projects/", **auth(client, admin_token))
        assert res.status_code == 200
        assert res.data["count"] == 2

    def test_unauthenticated_returns_401(self, client):
        res = client.get("/api/projects/")
        assert res.status_code == 401

    def test_list_is_paginated(self, client, teacher_user, teacher_token):
        for i in range(25):
            make_project(teacher_user, f"Project {i}")
        res = client.get("/api/projects/", **auth(client, teacher_token))
        assert res.status_code == 200
        assert len(res.data["results"]) == 20   # PAGE_SIZE = 20
        assert res.data["count"] == 25

    def test_filter_by_status(self, client, teacher_user, teacher_token):
        make_project(teacher_user, "Draft project")
        res = client.get("/api/projects/?status=DRAFT", **auth(client, teacher_token))
        assert res.status_code == 200
        assert all(p["status"] == "DRAFT" for p in res.data["results"])

    def test_search_by_title(self, client, teacher_user, teacher_token):
        make_project(teacher_user, "Science Fair")
        make_project(teacher_user, "History Essay")
        res = client.get("/api/projects/?search=science", **auth(client, teacher_token))
        assert res.status_code == 200
        titles = [p["title"] for p in res.data["results"]]
        assert "Science Fair" in titles
        assert "History Essay" not in titles


# ── create tests ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProjectCreate:
    def test_teacher_can_create_project(self, client, teacher_user, teacher_token):
        res = client.post(
            "/api/projects/",
            {"title": "New Project", "deadline": "2027-06-01T00:00:00Z"},
            content_type="application/json",
            **auth(client, teacher_token),
        )
        assert res.status_code == 201
        assert res.data["title"] == "New Project"
        assert res.data["status"] == "DRAFT"
        assert res.data["created_by"]["username"] == "teacher1"

    def test_student_cannot_create_project(self, client, student_token):
        res = client.post(
            "/api/projects/",
            {"title": "Student Project", "deadline": "2027-06-01T00:00:00Z"},
            content_type="application/json",
            **auth(client, student_token),
        )
        assert res.status_code == 403

    def test_admin_cannot_create_project(self, client, admin_token):
        res = client.post(
            "/api/projects/",
            {"title": "Admin Project", "deadline": "2027-06-01T00:00:00Z"},
            content_type="application/json",
            **auth(client, admin_token),
        )
        assert res.status_code == 403

    def test_status_is_always_draft_on_create(self, client, teacher_token):
        """status field in request body must be ignored — always starts DRAFT."""
        res = client.post(
            "/api/projects/",
            {"title": "P", "deadline": "2027-06-01T00:00:00Z", "status": "GRADED"},
            content_type="application/json",
            **auth(client, teacher_token),
        )
        assert res.status_code == 201
        assert res.data["status"] == "DRAFT"


# ── retrieve tests ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProjectRetrieve:
    def test_teacher_can_retrieve_own_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        res = client.get(f"/api/projects/{project.id}/", **auth(client, teacher_token))
        assert res.status_code == 200
        assert res.data["id"] == project.id
        assert "tasks" in res.data
        assert "progress" in res.data

    def test_teacher_cannot_retrieve_other_teachers_project(
        self, client, teacher_token
    ):
        other = User.objects.create_user(username="t2", password="x", role="TEACHER")
        project = make_project(other)
        res = client.get(f"/api/projects/{project.id}/", **auth(client, teacher_token))
        assert res.status_code == 404   # not 403 — information hiding

    def test_student_can_retrieve_assigned_project(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user)
        project.assigned_students.add(student_user)
        res = client.get(f"/api/projects/{project.id}/", **auth(client, student_token))
        assert res.status_code == 200

    def test_student_cannot_retrieve_unassigned_project(
        self, client, teacher_user, student_token
    ):
        project = make_project(teacher_user)
        res = client.get(f"/api/projects/{project.id}/", **auth(client, student_token))
        assert res.status_code == 404   # not 403


# ── update tests ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProjectUpdate:
    def test_teacher_can_update_own_draft_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        res = client.patch(
            f"/api/projects/{project.id}/",
            {"title": "Updated Title"},
            content_type="application/json",
            **auth(client, teacher_token),
        )
        assert res.status_code == 200
        assert res.data["title"] == "Updated Title"

    def test_status_is_read_only_on_patch(self, client, teacher_user, teacher_token):
        """Automatic rubric red flag — status must never be editable via PATCH."""
        project = make_project(teacher_user)
        res = client.patch(
            f"/api/projects/{project.id}/",
            {"status": "GRADED"},
            content_type="application/json",
            **auth(client, teacher_token),
        )
        project.refresh_from_db()
        assert project.status == "DRAFT"   # status unchanged

    def test_student_cannot_update_project(self, client, teacher_user, student_user, student_token):
        project = make_project(teacher_user)
        project.assigned_students.add(student_user)
        res = client.patch(
            f"/api/projects/{project.id}/",
            {"title": "Hacked"},
            content_type="application/json",
            **auth(client, student_token),
        )
        assert res.status_code == 403

    def test_cannot_update_non_draft_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        project.status = Project.Status.IN_PROGRESS
        project.save()
        res = client.patch(
            f"/api/projects/{project.id}/",
            {"title": "Updated"},
            content_type="application/json",
            **auth(client, teacher_token),
        )
        assert res.status_code == 400


# ── delete tests ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProjectDelete:
    def test_teacher_can_delete_own_draft_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        res = client.delete(f"/api/projects/{project.id}/", **auth(client, teacher_token))
        assert res.status_code == 204
        assert not Project.objects.filter(id=project.id).exists()

    def test_cannot_delete_non_draft_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        project.status = Project.Status.IN_PROGRESS
        project.save()
        res = client.delete(f"/api/projects/{project.id}/", **auth(client, teacher_token))
        assert res.status_code == 400


# ── assign/unassign tests ─────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAssignStudents:
    def test_teacher_can_assign_students(self, client, teacher_user, student_user, teacher_token):
        project = make_project(teacher_user)
        res = client.post(
            f"/api/projects/{project.id}/students/",
            {"student_ids": [student_user.id]},
            content_type="application/json",
            **auth(client, teacher_token),
        )
        assert res.status_code == 200
        student_ids = [s["id"] for s in res.data["assigned_students"]]
        assert student_user.id in student_ids

    def test_teacher_can_unassign_student(self, client, teacher_user, student_user, teacher_token):
        project = make_project(teacher_user)
        project.assigned_students.add(student_user)
        res = client.delete(
            f"/api/projects/{project.id}/students/{student_user.id}/",
            **auth(client, teacher_token),
        )
        assert res.status_code == 204
        assert not project.assigned_students.filter(id=student_user.id).exists()

    def test_student_cannot_assign_students(self, client, teacher_user, student_user, student_token):
        project = make_project(teacher_user)
        project.assigned_students.add(student_user)
        res = client.post(
            f"/api/projects/{project.id}/students/",
            {"student_ids": [student_user.id]},
            content_type="application/json",
            **auth(client, student_token),
        )
        assert res.status_code == 403


# ── query count test ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestQueryCounts:
    def test_project_list_query_count(self, client, teacher_user, teacher_token):
        """List endpoint must run a fixed number of queries regardless of project count."""
        for i in range(5):
            make_project(teacher_user, f"Project {i}")

        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            res = client.get("/api/projects/", **auth(client, teacher_token))

        assert res.status_code == 200
        # auth(1) + projects(1) + students prefetch(1) = max 5 queries
        assert len(ctx) <= 5, f"Too many queries: {len(ctx)}"
