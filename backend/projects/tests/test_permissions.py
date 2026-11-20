"""
Regression tests for Step 12 — permissions and scoped querysets.

Tests here are unit tests (Python only, no HTTP).
HTTP-level 403/404 tests are in test_projects.py (Step 13).

Run: docker compose exec backend pytest projects/tests/test_permissions.py -v
"""
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from projects.models import Project
from projects.selectors import get_projects_for_user

User = get_user_model()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def teacher2(db):
    return User.objects.create_user(
        username="teacher2", password="teacher123", role="TEACHER"
    )


@pytest.fixture
def student2(db):
    return User.objects.create_user(
        username="student2", password="student123", role="STUDENT"
    )


@pytest.fixture
def project_by_teacher1(db, teacher_user):
    return Project.objects.create(
        title="Teacher1 Project",
        created_by=teacher_user,
        deadline=timezone.now() + timezone.timedelta(days=30),
    )


@pytest.fixture
def project_by_teacher2(db, teacher2):
    return Project.objects.create(
        title="Teacher2 Project",
        created_by=teacher2,
        deadline=timezone.now() + timezone.timedelta(days=30),
    )


# ── admin sees everything ─────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAdminScope:
    def test_admin_sees_all_projects(
        self, admin_user, project_by_teacher1, project_by_teacher2
    ):
        """Admin queryset includes every project regardless of owner."""
        qs = get_projects_for_user(admin_user)
        assert qs.count() == 2

    def test_admin_sees_projects_from_all_teachers(
        self, admin_user, teacher_user, teacher2,
        project_by_teacher1, project_by_teacher2
    ):
        ids = set(qs.values_list("id", flat=True)
                  for qs in [get_projects_for_user(admin_user)])
        # both project ids are in admin's queryset
        qs = get_projects_for_user(admin_user)
        project_ids = list(qs.values_list("id", flat=True))
        assert project_by_teacher1.id in project_ids
        assert project_by_teacher2.id in project_ids


# ── teacher sees only their own ───────────────────────────────────────────────

@pytest.mark.django_db
class TestTeacherScope:
    def test_teacher_sees_own_projects_only(
        self, teacher_user, teacher2,
        project_by_teacher1, project_by_teacher2
    ):
        """A teacher's queryset never includes another teacher's project."""
        qs = get_projects_for_user(teacher_user)
        ids = list(qs.values_list("id", flat=True))
        assert project_by_teacher1.id in ids
        assert project_by_teacher2.id not in ids

    def test_teacher2_sees_own_projects_only(
        self, teacher_user, teacher2,
        project_by_teacher1, project_by_teacher2
    ):
        qs = get_projects_for_user(teacher2)
        ids = list(qs.values_list("id", flat=True))
        assert project_by_teacher2.id in ids
        assert project_by_teacher1.id not in ids

    def test_teacher_with_no_projects_sees_empty(self, teacher2):
        """Teacher with zero projects gets an empty queryset, not an error."""
        qs = get_projects_for_user(teacher2)
        assert qs.count() == 0


# ── student sees only assigned ────────────────────────────────────────────────

@pytest.mark.django_db
class TestStudentScope:
    def test_student_sees_assigned_project(
        self, student_user, project_by_teacher1
    ):
        """Student only sees projects they are assigned to."""
        project_by_teacher1.assigned_students.add(student_user)
        qs = get_projects_for_user(student_user)
        assert project_by_teacher1.id in list(qs.values_list("id", flat=True))

    def test_student_does_not_see_unassigned_project(
        self, student_user, project_by_teacher1
    ):
        """Student gets empty queryset for projects they are not assigned to."""
        qs = get_projects_for_user(student_user)
        assert project_by_teacher1.id not in list(qs.values_list("id", flat=True))

    def test_student_sees_multiple_assigned_projects(
        self, student_user, project_by_teacher1, project_by_teacher2
    ):
        project_by_teacher1.assigned_students.add(student_user)
        project_by_teacher2.assigned_students.add(student_user)
        qs = get_projects_for_user(student_user)
        assert qs.count() == 2

    def test_student_with_no_assignments_sees_empty(self, student_user):
        qs = get_projects_for_user(student_user)
        assert qs.count() == 0


# ── task tree selector ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestGetTaskTree:
    def test_returns_empty_list_for_project_with_no_tasks(
        self, project_by_teacher1
    ):
        from projects.selectors import get_task_tree
        result = get_task_tree(project_by_teacher1.id)
        assert result == []

    def test_root_tasks_have_children_attribute(
        self, project_by_teacher1
    ):
        """Every task returned has a ._children list (even if empty)."""
        from projects.models import Task
        from projects.selectors import get_task_tree
        from decimal import Decimal

        task = Task.objects.create(
            project=project_by_teacher1,
            title="Root task",
            weight=Decimal("100.00"),
        )
        roots = get_task_tree(project_by_teacher1.id)
        assert len(roots) == 1
        assert hasattr(roots[0], "_children")
        assert roots[0]._children == []

    def test_tree_assembled_in_one_query(self, project_by_teacher1):
        """get_task_tree must run exactly ONE database query — no N+1."""
        from projects.models import Task
        from projects.selectors import get_task_tree
        from decimal import Decimal
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        parent = Task.objects.create(
            project=project_by_teacher1,
            title="Parent",
            weight=Decimal("100.00"),
        )
        Task.objects.create(
            project=project_by_teacher1,
            title="Child",
            weight=Decimal("100.00"),
            parent_task=parent,
        )

        with CaptureQueriesContext(connection) as ctx:
            get_task_tree(project_by_teacher1.id)

        assert len(ctx) == 1, (
            f"Expected 1 query for task tree, got {len(ctx)}. "
            "This is an N+1 violation."
        )

    def test_children_attached_to_correct_parent(self, project_by_teacher1):
        """Children are attached to their parent, not to the root list."""
        from projects.models import Task
        from projects.selectors import get_task_tree
        from decimal import Decimal

        parent = Task.objects.create(
            project=project_by_teacher1,
            title="Parent",
            weight=Decimal("100.00"),
        )
        child = Task.objects.create(
            project=project_by_teacher1,
            title="Child",
            weight=Decimal("100.00"),
            parent_task=parent,
        )

        roots = get_task_tree(project_by_teacher1.id)
        assert len(roots) == 1          # only parent at root
        assert len(roots[0]._children) == 1
        assert roots[0]._children[0].id == child.id
