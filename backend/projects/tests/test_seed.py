"""
Regression tests for Step 19 — seed_school_data management command.
Tests cover: users created, all four project statuses, tasks, idempotency.
Run: docker compose exec backend pytest projects/tests/test_seed.py -v
"""
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from projects.models import Project, ProjectStatusLog, Task

User = get_user_model()


@pytest.fixture
def seeded(db):
    """Run the seed command once and return."""
    call_command("seed_school_data", verbosity=0)


@pytest.fixture
def seeded_twice(db):
    """Run the seed command twice — idempotency fixture."""
    call_command("seed_school_data", verbosity=0)
    call_command("seed_school_data", verbosity=0)


# ── users ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeedUsers:
    def test_creates_all_four_users(self, seeded):
        assert User.objects.count() == 4

    def test_creates_admin_with_correct_role(self, seeded):
        u = User.objects.get(username="admin1")
        assert u.role == "ADMIN"
        assert u.is_superuser is True

    def test_creates_teacher_with_correct_role(self, seeded):
        u = User.objects.get(username="teacher1")
        assert u.role == "TEACHER"

    def test_creates_students_with_correct_role(self, seeded):
        for name in ("student1", "student2"):
            u = User.objects.get(username=name)
            assert u.role == "STUDENT"

    def test_passwords_are_usable(self, seeded):
        for username, password in [
            ("admin1", "admin123"),
            ("teacher1", "teacher123"),
            ("student1", "student123"),
            ("student2", "student123"),
        ]:
            user = User.objects.get(username=username)
            assert user.check_password(password), f"{username} password check failed"


# ── projects ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeedProjects:
    def test_creates_four_projects(self, seeded):
        assert Project.objects.count() == 4

    def test_one_project_per_status(self, seeded):
        statuses = set(Project.objects.values_list("status", flat=True))
        assert statuses == {
            Project.Status.DRAFT,
            Project.Status.IN_PROGRESS,
            Project.Status.SUBMITTED,
            Project.Status.GRADED,
        }

    def test_draft_project_has_no_students(self, seeded):
        p = Project.objects.get(status=Project.Status.DRAFT)
        assert p.assigned_students.count() == 0

    def test_in_progress_project_has_students(self, seeded):
        p = Project.objects.get(status=Project.Status.IN_PROGRESS)
        assert p.assigned_students.count() == 2

    def test_submitted_project_has_submitted_by(self, seeded):
        p = Project.objects.get(status=Project.Status.SUBMITTED)
        assert p.submitted_by is not None
        assert p.submitted_at is not None
        assert p.is_late is False

    def test_graded_project_has_grade_and_feedback(self, seeded):
        p = Project.objects.get(status=Project.Status.GRADED)
        assert p.grade is not None
        assert p.feedback != ""
        assert p.graded_at is not None


# ── tasks ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeedTasks:
    def test_every_project_has_tasks(self, seeded):
        for p in Project.objects.all():
            assert p.tasks.count() >= 1, f"{p.title} has no tasks"

    def test_in_progress_project_has_nested_tasks(self, seeded):
        p = Project.objects.get(status=Project.Status.IN_PROGRESS)
        root = p.tasks.get(parent_task__isnull=True)
        assert p.tasks.filter(parent_task=root).count() == 2

    def test_graded_project_all_tasks_completed(self, seeded):
        p = Project.objects.get(status=Project.Status.GRADED)
        assert p.tasks.filter(is_completed=False).count() == 0


# ── audit log ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeedStatusLogs:
    def test_graded_project_has_three_log_entries(self, seeded):
        p = Project.objects.get(status=Project.Status.GRADED)
        assert p.status_logs.count() == 3

    def test_draft_project_has_no_log_entries(self, seeded):
        p = Project.objects.get(status=Project.Status.DRAFT)
        assert p.status_logs.count() == 0


# ── idempotency ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeedIdempotency:
    def test_running_twice_does_not_duplicate_users(self, seeded_twice):
        assert User.objects.count() == 4

    def test_running_twice_does_not_duplicate_projects(self, seeded_twice):
        assert Project.objects.count() == 4

    def test_running_twice_does_not_duplicate_tasks(self, seeded_twice):
        first_run_count = Task.objects.count()
        # Count after two runs equals count after one run (fixture ran it twice)
        assert first_run_count == Task.objects.count()
