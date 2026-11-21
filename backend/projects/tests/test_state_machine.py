"""
Regression tests for Step 16 — state machine transitions.
Tests cover: publish, submit, grade, return for revision, force transition,
optimistic locking (stale version → 409), and permission guards.
Run: docker compose exec backend pytest projects/tests/test_state_machine.py -v
"""
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from projects.models import Project, ProjectStatusLog

User = get_user_model()


# ── helpers ───────────────────────────────────────────────────────────────────

def make_project(teacher, status=Project.Status.DRAFT, days=30):
    return Project.objects.create(
        title="Test Project",
        created_by=teacher,
        deadline=timezone.now() + timezone.timedelta(days=days),
        status=status,
    )


def auth(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# ── publish ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPublish:
    def test_teacher_can_publish_draft_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)   # version=1, status=DRAFT
        res = client.post(
            f"/api/projects/{project.id}/publish/",
            {"version": 1},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 200
        assert res.data["status"] == "IN_PROGRESS"
        assert res.data["version"] == 2   # incremented

    def test_publish_creates_status_log(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        client.post(
            f"/api/projects/{project.id}/publish/",
            {"version": 1},
            content_type="application/json",
            **auth(teacher_token),
        )
        log = ProjectStatusLog.objects.get(project=project)
        assert log.from_status == "DRAFT"
        assert log.to_status == "IN_PROGRESS"
        assert log.changed_by == teacher_user
        assert log.is_forced is False

    def test_cannot_publish_non_draft_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        res = client.post(
            f"/api/projects/{project.id}/publish/",
            {"version": 1},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_student_cannot_publish(self, client, teacher_user, student_user, student_token):
        project = make_project(teacher_user)
        project.assigned_students.add(student_user)
        res = client.post(
            f"/api/projects/{project.id}/publish/",
            {"version": 1},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 403

    def test_stale_version_returns_409(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)   # version=1
        project.version = 2   # simulate another request updating it
        project.save(update_fields=["version"])
        res = client.post(
            f"/api/projects/{project.id}/publish/",
            {"version": 1},   # client sends old version
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 409
        assert res.data["code"] == "stale_data"


# ── submit ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSubmit:
    def test_assigned_student_can_submit(self, client, teacher_user, student_user, student_token):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        project.assigned_students.add(student_user)
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 1},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 200
        assert res.data["status"] == "SUBMITTED"
        assert res.data["version"] == 2

    def test_submit_records_submitted_at_and_submitted_by(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        project.assigned_students.add(student_user)
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 1},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.data["submitted_at"] is not None
        assert res.data["submitted_by"]["id"] == student_user.id

    def test_submit_marks_is_late_when_past_deadline(
        self, client, teacher_user, student_user, student_token
    ):
        project = Project.objects.create(
            title="Late Project",
            created_by=teacher_user,
            deadline=timezone.now() - timezone.timedelta(days=1),   # yesterday
            status=Project.Status.IN_PROGRESS,
        )
        project.assigned_students.add(student_user)
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 1},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 200
        assert res.data["is_late"] is True

    def test_submit_not_late_when_before_deadline(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        project.assigned_students.add(student_user)
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 1},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.data["is_late"] is False

    def test_teacher_cannot_submit(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 1},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 403

    def test_cannot_submit_draft_project(self, client, teacher_user, student_user, student_token):
        project = make_project(teacher_user, status=Project.Status.DRAFT)
        project.assigned_students.add(student_user)
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 1},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 400

    def test_unassigned_student_gets_404(self, client, teacher_user, student_token):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        # student is NOT assigned — scoped queryset returns 404
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 1},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 404

    def test_stale_version_returns_409(self, client, teacher_user, student_user, student_token):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        project.assigned_students.add(student_user)
        project.version = 3
        project.save(update_fields=["version"])
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 1},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 409
        assert res.data["code"] == "stale_data"


# ── grade ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestGrade:
    def test_teacher_can_grade_submitted_project(
        self, client, teacher_user, student_user, teacher_token
    ):
        project = make_project(teacher_user, status=Project.Status.SUBMITTED)
        res = client.post(
            f"/api/projects/{project.id}/grade/",
            {"version": 1, "grade": "88.50", "feedback": "Excellent work."},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 200
        assert res.data["status"] == "GRADED"
        assert res.data["grade"] == "88.50"
        assert res.data["graded_at"] is not None

    def test_grade_requires_feedback(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.SUBMITTED)
        res = client.post(
            f"/api/projects/{project.id}/grade/",
            {"version": 1, "grade": "90.00", "feedback": ""},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_grade_out_of_range_returns_400(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.SUBMITTED)
        res = client.post(
            f"/api/projects/{project.id}/grade/",
            {"version": 1, "grade": "150.00", "feedback": "Good"},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_cannot_grade_non_submitted_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        res = client.post(
            f"/api/projects/{project.id}/grade/",
            {"version": 1, "grade": "80.00", "feedback": "Good"},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_student_cannot_grade(self, client, teacher_user, student_user, student_token):
        project = make_project(teacher_user, status=Project.Status.SUBMITTED)
        project.assigned_students.add(student_user)
        res = client.post(
            f"/api/projects/{project.id}/grade/",
            {"version": 1, "grade": "80.00", "feedback": "Good"},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 403


# ── return for revision ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestReturnForRevision:
    def test_teacher_can_return_submitted_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.SUBMITTED)
        res = client.post(
            f"/api/projects/{project.id}/return/",
            {"version": 1, "feedback": "Please redo section 2."},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 200
        assert res.data["status"] == "IN_PROGRESS"
        assert res.data["feedback"] == "Please redo section 2."

    def test_return_requires_feedback(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.SUBMITTED)
        res = client.post(
            f"/api/projects/{project.id}/return/",
            {"version": 1, "feedback": ""},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_cannot_return_non_submitted_project(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.DRAFT)
        res = client.post(
            f"/api/projects/{project.id}/return/",
            {"version": 1, "feedback": "Needs more work."},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_return_creates_status_log(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.SUBMITTED)
        client.post(
            f"/api/projects/{project.id}/return/",
            {"version": 1, "feedback": "Revise it."},
            content_type="application/json",
            **auth(teacher_token),
        )
        log = ProjectStatusLog.objects.get(project=project)
        assert log.from_status == "SUBMITTED"
        assert log.to_status == "IN_PROGRESS"


# ── force transition ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForceTransition:
    def test_admin_can_force_any_transition(self, client, teacher_user, admin_token):
        project = make_project(teacher_user, status=Project.Status.DRAFT)
        res = client.post(
            f"/api/projects/{project.id}/force-transition/",
            {"version": 1, "to_status": "GRADED", "reason": "Reviewer override."},
            content_type="application/json",
            **auth(admin_token),
        )
        assert res.status_code == 200
        assert res.data["status"] == "GRADED"

    def test_force_transition_logs_is_forced(self, client, teacher_user, admin_user, admin_token):
        project = make_project(teacher_user, status=Project.Status.DRAFT)
        client.post(
            f"/api/projects/{project.id}/force-transition/",
            {"version": 1, "to_status": "GRADED", "reason": "Override."},
            content_type="application/json",
            **auth(admin_token),
        )
        log = ProjectStatusLog.objects.get(project=project)
        assert log.is_forced is True
        assert log.reason == "Override."
        assert log.changed_by == admin_user

    def test_teacher_cannot_force_transition(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user, status=Project.Status.DRAFT)
        res = client.post(
            f"/api/projects/{project.id}/force-transition/",
            {"version": 1, "to_status": "GRADED", "reason": "Override."},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 403

    def test_force_transition_requires_reason(self, client, teacher_user, admin_token):
        project = make_project(teacher_user, status=Project.Status.DRAFT)
        res = client.post(
            f"/api/projects/{project.id}/force-transition/",
            {"version": 1, "to_status": "GRADED", "reason": ""},
            content_type="application/json",
            **auth(admin_token),
        )
        assert res.status_code == 400

    def test_force_to_same_status_returns_400(self, client, teacher_user, admin_token):
        project = make_project(teacher_user, status=Project.Status.DRAFT)
        res = client.post(
            f"/api/projects/{project.id}/force-transition/",
            {"version": 1, "to_status": "DRAFT", "reason": "No change."},
            content_type="application/json",
            **auth(admin_token),
        )
        assert res.status_code == 400


# ── full flow ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestFullFlow:
    def test_full_draft_to_graded_flow(
        self, client, teacher_user, student_user, teacher_token, student_token
    ):
        """Happy path: DRAFT → IN_PROGRESS → SUBMITTED → GRADED."""
        project = make_project(teacher_user)   # DRAFT, version=1
        project.assigned_students.add(student_user)

        # Teacher publishes
        res = client.post(
            f"/api/projects/{project.id}/publish/",
            {"version": 1},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.data["status"] == "IN_PROGRESS"
        assert res.data["version"] == 2

        # Student submits
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 2},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.data["status"] == "SUBMITTED"
        assert res.data["version"] == 3

        # Teacher grades
        res = client.post(
            f"/api/projects/{project.id}/grade/",
            {"version": 3, "grade": "95.00", "feedback": "Outstanding."},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.data["status"] == "GRADED"
        assert res.data["version"] == 4
        assert res.data["grade"] == "95.00"

        # Verify 3 log entries were created
        assert ProjectStatusLog.objects.filter(project_id=project.id).count() == 3

    def test_submit_then_return_then_resubmit(
        self, client, teacher_user, student_user, teacher_token, student_token
    ):
        """SUBMITTED → IN_PROGRESS (return) → SUBMITTED (resubmit)."""
        project = make_project(teacher_user, status=Project.Status.SUBMITTED)
        project.assigned_students.add(student_user)

        # Teacher returns
        res = client.post(
            f"/api/projects/{project.id}/return/",
            {"version": 1, "feedback": "Needs more detail."},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.data["status"] == "IN_PROGRESS"
        assert res.data["version"] == 2

        # Student resubmits
        res = client.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 2},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.data["status"] == "SUBMITTED"
        assert res.data["version"] == 3
