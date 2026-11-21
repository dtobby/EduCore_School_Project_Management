import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from projects.models import Project, Task

User = get_user_model()
pytestmark = pytest.mark.django_db

URL = "/api/schedule/"


def make_project(teacher, **kwargs):
    defaults = {
        "title": "Test Project",
        "deadline": timezone.now() + timedelta(days=10),
        "status": Project.Status.DRAFT,
    }
    defaults.update(kwargs)
    return Project.objects.create(created_by=teacher, **defaults)


# ── student schedule ──────────────────────────────────────────────────────────

class TestStudentSchedule:
    def test_sees_in_progress_deadline(self, client, student_user, student_token, teacher_user):
        p = make_project(teacher_user, status=Project.Status.IN_PROGRESS, title="Science Fair")
        p.assigned_students.add(student_user)

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {student_token}")

        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["type"] == "deadline"
        assert events[0]["project_id"] == p.id
        assert events[0]["title"] == "Science Fair"

    def test_does_not_see_draft_project(self, client, student_user, student_token, teacher_user):
        p = make_project(teacher_user, status=Project.Status.DRAFT)
        p.assigned_students.add(student_user)

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {student_token}")

        assert resp.json() == []

    def test_sees_incomplete_task_with_due_date(self, client, student_user, student_token, teacher_user):
        p = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        p.assigned_students.add(student_user)
        task = Task.objects.create(
            project=p, title="Research Phase", weight="100.00",
            due_date=timezone.now() + timedelta(days=5),
        )

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {student_token}")

        task_events = [e for e in resp.json() if e["type"] == "task_due"]
        assert len(task_events) == 1
        assert task_events[0]["title"] == "Research Phase"
        assert task_events[0]["project_id"] == p.id

    def test_does_not_see_completed_task(self, client, student_user, student_token, teacher_user):
        p = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        p.assigned_students.add(student_user)
        Task.objects.create(
            project=p, title="Done Task", weight="100.00",
            due_date=timezone.now() + timedelta(days=5),
            is_completed=True,
        )

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {student_token}")

        task_events = [e for e in resp.json() if e["type"] == "task_due"]
        assert task_events == []

    def test_does_not_see_unassigned_project(self, client, student_user, student_token, teacher_user):
        make_project(teacher_user, status=Project.Status.IN_PROGRESS)

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {student_token}")

        assert resp.json() == []

    def test_date_range_excludes_far_future_deadline(self, client, student_user, student_token, teacher_user):
        p = make_project(
            teacher_user, status=Project.Status.IN_PROGRESS,
            deadline=timezone.now() + timedelta(days=60),
        )
        p.assigned_students.add(student_user)

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {student_token}")

        assert resp.json() == []

    def test_task_without_due_date_excluded(self, client, student_user, student_token, teacher_user):
        p = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        p.assigned_students.add(student_user)
        Task.objects.create(project=p, title="No Due Date", weight="100.00")

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {student_token}")

        task_events = [e for e in resp.json() if e["type"] == "task_due"]
        assert task_events == []


# ── teacher schedule ──────────────────────────────────────────────────────────

class TestTeacherSchedule:
    def test_sees_own_project_deadline(self, client, teacher_user, teacher_token):
        p = make_project(teacher_user, title="Art Portfolio")

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {teacher_token}")

        events = resp.json()
        assert len(events) == 1
        assert events[0]["type"] == "deadline"
        assert events[0]["project_id"] == p.id

    def test_sees_submitted_project_in_queue(self, client, teacher_user, teacher_token):
        p = make_project(
            teacher_user, title="Math Investigation",
            status=Project.Status.SUBMITTED,
            submitted_at=timezone.now() - timedelta(days=2),
        )

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {teacher_token}")

        submission_events = [e for e in resp.json() if e["type"] == "submission"]
        assert len(submission_events) == 1
        assert submission_events[0]["project_id"] == p.id
        assert submission_events[0]["title"] == "Math Investigation"

    def test_does_not_see_other_teacher_project(self, client, teacher_user, teacher_token, db):
        other = User.objects.create_user(
            username="teacher2", password="pass123", role="TEACHER"
        )
        make_project(other, status=Project.Status.IN_PROGRESS)

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {teacher_token}")

        assert resp.json() == []

    def test_date_range_excludes_far_future_deadline(self, client, teacher_user, teacher_token):
        make_project(teacher_user, deadline=timezone.now() + timedelta(days=60))

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {teacher_token}")

        assert resp.json() == []

    def test_submission_queue_always_visible_outside_deadline_range(self, client, teacher_user, teacher_token):
        """Submissions appear regardless of date range — they're a pending work queue."""
        make_project(
            teacher_user,
            status=Project.Status.SUBMITTED,
            submitted_at=timezone.now() - timedelta(days=5),
            deadline=timezone.now() + timedelta(days=60),  # deadline outside default range
        )

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {teacher_token}")

        submission_events = [e for e in resp.json() if e["type"] == "submission"]
        assert len(submission_events) == 1


# ── auth ──────────────────────────────────────────────────────────────────────

class TestScheduleAuth:
    def test_unauthenticated_returns_401(self, client):
        resp = client.get(URL)
        assert resp.status_code == 401

    def test_admin_returns_empty_list(self, client, admin_token):
        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        assert resp.status_code == 200
        assert resp.json() == []


# ── ordering ──────────────────────────────────────────────────────────────────

class TestScheduleOrder:
    def test_events_sorted_by_date_ascending(self, client, student_user, student_token, teacher_user):
        p1 = make_project(
            teacher_user, title="Late Project",
            status=Project.Status.IN_PROGRESS,
            deadline=timezone.now() + timedelta(days=20),
        )
        p2 = make_project(
            teacher_user, title="Soon Project",
            status=Project.Status.IN_PROGRESS,
            deadline=timezone.now() + timedelta(days=5),
        )
        p1.assigned_students.add(student_user)
        p2.assigned_students.add(student_user)

        resp = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {student_token}")

        events = resp.json()
        assert len(events) == 2
        assert events[0]["title"] == "Soon Project"
        assert events[1]["title"] == "Late Project"


# ── query params ──────────────────────────────────────────────────────────────

class TestScheduleParams:
    def test_invalid_date_param_returns_400(self, client, student_token):
        resp = client.get(f"{URL}?from=not-a-date", HTTP_AUTHORIZATION=f"Bearer {student_token}")
        assert resp.status_code == 400

    def test_custom_range_includes_matching_event(self, client, student_user, student_token, teacher_user):
        # Deadline at day 15 — inside custom range [day 10, day 20]
        p = make_project(
            teacher_user, status=Project.Status.IN_PROGRESS,
            deadline=timezone.now() + timedelta(days=15),
        )
        p.assigned_students.add(student_user)

        from_dt = (timezone.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        to_dt = (timezone.now() + timedelta(days=20)).strftime("%Y-%m-%d")
        resp = client.get(
            f"{URL}?from={from_dt}&to={to_dt}",
            HTTP_AUTHORIZATION=f"Bearer {student_token}",
        )

        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_custom_range_excludes_nonmatching_event(self, client, student_user, student_token, teacher_user):
        # Deadline at day 5 — outside custom range [day 10, day 20]
        p = make_project(
            teacher_user, status=Project.Status.IN_PROGRESS,
            deadline=timezone.now() + timedelta(days=5),
        )
        p.assigned_students.add(student_user)

        from_dt = (timezone.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        to_dt = (timezone.now() + timedelta(days=20)).strftime("%Y-%m-%d")
        resp = client.get(
            f"{URL}?from={from_dt}&to={to_dt}",
            HTTP_AUTHORIZATION=f"Bearer {student_token}",
        )

        assert resp.json() == []
