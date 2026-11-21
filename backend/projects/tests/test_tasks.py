"""
Regression tests for Step 14 — Task CRUD.
Tests cover: list (tree), create, retrieve, update, delete, bulk weights, toggle completion.
Run: docker compose exec backend pytest projects/tests/test_tasks.py -v
"""
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from projects.models import Project, Task

User = get_user_model()

# ── helpers ───────────────────────────────────────────────────────────────────

def make_project(teacher, status=Project.Status.DRAFT):
    return Project.objects.create(
        title="Test Project",
        created_by=teacher,
        deadline=timezone.now() + timezone.timedelta(days=30),
        status=status,
    )


def make_task(project, title="Root Task", weight="100.00", parent=None, order=0):
    return Task.objects.create(
        project=project,
        title=title,
        weight=weight,
        parent_task=parent,
        order=order,
    )


def auth(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


BASE = "/api/projects/{project_id}/tasks/"
DETAIL = "/api/projects/{project_id}/tasks/{task_id}/"
WEIGHTS = "/api/projects/{project_id}/tasks/weights/"
TOGGLE = "/api/projects/{project_id}/tasks/{task_id}/toggle/"


# ── list ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTaskList:
    def test_returns_task_tree(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        root = make_task(project, "Root")
        make_task(project, "Child", parent=root)
        url = BASE.format(project_id=project.id)
        res = client.get(url, **auth(teacher_token))
        assert res.status_code == 200
        assert len(res.data) == 1              # one root
        assert len(res.data[0]["children"]) == 1  # one child nested

    def test_unauthenticated_returns_401(self, client, teacher_user):
        project = make_project(teacher_user)
        res = client.get(BASE.format(project_id=project.id))
        assert res.status_code == 401

    def test_student_sees_assigned_project_tasks(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user)
        project.assigned_students.add(student_user)
        make_task(project, "Task A")
        url = BASE.format(project_id=project.id)
        res = client.get(url, **auth(student_token))
        assert res.status_code == 200
        assert len(res.data) == 1

    def test_student_cannot_list_unassigned_project_tasks(
        self, client, teacher_user, student_token
    ):
        project = make_project(teacher_user)
        make_task(project)
        url = BASE.format(project_id=project.id)
        res = client.get(url, **auth(student_token))
        assert res.status_code == 404


# ── create ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTaskCreate:
    def test_teacher_can_create_root_task(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        url = BASE.format(project_id=project.id)
        res = client.post(
            url,
            {"title": "Research", "weight": "60.00"},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 201
        assert res.data["title"] == "Research"
        assert res.data["weight"] == "60.00"

    def test_teacher_can_create_child_task(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        root = make_task(project, "Root", weight="100.00")
        url = BASE.format(project_id=project.id)
        res = client.post(
            url,
            {"title": "Child", "weight": "50.00", "parent_task": root.id},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 201
        assert res.data["parent_task"] == root.id

    def test_cannot_create_task_on_non_draft_project(
        self, client, teacher_user, teacher_token
    ):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        url = BASE.format(project_id=project.id)
        res = client.post(
            url,
            {"title": "Late Task", "weight": "100.00"},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_cannot_exceed_max_depth(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        l1 = make_task(project, "L1")
        l2 = make_task(project, "L2", parent=l1)
        l3 = make_task(project, "L3", parent=l2)
        # Trying to add a child to l3 would be depth 4 — forbidden
        url = BASE.format(project_id=project.id)
        res = client.post(
            url,
            {"title": "L4", "weight": "50.00", "parent_task": l3.id},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_level3_child_is_allowed(self, client, teacher_user, teacher_token):
        """Depth 3 is the maximum — it must be allowed."""
        project = make_project(teacher_user)
        l1 = make_task(project, "L1")
        l2 = make_task(project, "L2", parent=l1)
        url = BASE.format(project_id=project.id)
        res = client.post(
            url,
            {"title": "L3", "weight": "50.00", "parent_task": l2.id},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 201

    def test_student_cannot_create_task(self, client, teacher_user, student_user, student_token):
        project = make_project(teacher_user)
        project.assigned_students.add(student_user)
        url = BASE.format(project_id=project.id)
        res = client.post(
            url,
            {"title": "Hack", "weight": "100.00"},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 403


# ── retrieve ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTaskRetrieve:
    def test_teacher_can_retrieve_task(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        task = make_task(project)
        url = DETAIL.format(project_id=project.id, task_id=task.id)
        res = client.get(url, **auth(teacher_token))
        assert res.status_code == 200
        assert res.data["id"] == task.id

    def test_student_cannot_retrieve_unassigned_project_task(
        self, client, teacher_user, student_token
    ):
        project = make_project(teacher_user)
        task = make_task(project)
        url = DETAIL.format(project_id=project.id, task_id=task.id)
        res = client.get(url, **auth(student_token))
        assert res.status_code == 404


# ── update ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTaskUpdate:
    def test_teacher_can_update_task_title(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        task = make_task(project)
        url = DETAIL.format(project_id=project.id, task_id=task.id)
        res = client.patch(
            url,
            {"title": "New Title"},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 200

    def test_cannot_update_task_on_non_draft_project(
        self, client, teacher_user, teacher_token
    ):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        task = make_task(project)
        url = DETAIL.format(project_id=project.id, task_id=task.id)
        res = client.patch(
            url,
            {"title": "Updated"},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_student_cannot_update_task(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user)
        project.assigned_students.add(student_user)
        task = make_task(project)
        url = DETAIL.format(project_id=project.id, task_id=task.id)
        res = client.patch(
            url,
            {"title": "Hacked"},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 403


# ── delete ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTaskDelete:
    def test_teacher_can_delete_task(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        task = make_task(project)
        url = DETAIL.format(project_id=project.id, task_id=task.id)
        res = client.delete(url, **auth(teacher_token))
        assert res.status_code == 204
        assert not Task.objects.filter(id=task.id).exists()

    def test_deleting_parent_cascades_to_children(
        self, client, teacher_user, teacher_token
    ):
        project = make_project(teacher_user)
        root = make_task(project, "Root")
        child = make_task(project, "Child", parent=root)
        url = DETAIL.format(project_id=project.id, task_id=root.id)
        client.delete(url, **auth(teacher_token))
        assert not Task.objects.filter(id=child.id).exists()

    def test_cannot_delete_task_on_non_draft_project(
        self, client, teacher_user, teacher_token
    ):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        task = make_task(project)
        url = DETAIL.format(project_id=project.id, task_id=task.id)
        res = client.delete(url, **auth(teacher_token))
        assert res.status_code == 400


# ── bulk weights ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBulkWeights:
    def test_teacher_can_bulk_update_weights(self, client, teacher_user, teacher_token):
        project = make_project(teacher_user)
        t1 = make_task(project, "T1", weight="50.00")
        t2 = make_task(project, "T2", weight="50.00")
        url = WEIGHTS.format(project_id=project.id)
        res = client.put(
            url,
            {"weights": [
                {"id": t1.id, "weight": "60.00"},
                {"id": t2.id, "weight": "40.00"},
            ]},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 200
        t1.refresh_from_db()
        t2.refresh_from_db()
        assert str(t1.weight) == "60.00"
        assert str(t2.weight) == "40.00"

    def test_bulk_weights_rejects_wrong_project_task(
        self, client, teacher_user, teacher_token
    ):
        other = User.objects.create_user(username="t2", password="x", role="TEACHER")
        project = make_project(teacher_user)
        other_task = make_task(make_project(other), weight="100.00")
        url = WEIGHTS.format(project_id=project.id)
        res = client.put(
            url,
            {"weights": [{"id": other_task.id, "weight": "50.00"}]},
            content_type="application/json",
            **auth(teacher_token),
        )
        assert res.status_code == 400

    def test_student_cannot_bulk_update_weights(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user)
        project.assigned_students.add(student_user)
        task = make_task(project, weight="100.00")
        url = WEIGHTS.format(project_id=project.id)
        res = client.put(
            url,
            {"weights": [{"id": task.id, "weight": "50.00"}]},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 403


# ── toggle completion ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestToggleCompletion:
    def test_student_can_complete_leaf_task(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        project.assigned_students.add(student_user)
        task = make_task(project)
        url = TOGGLE.format(project_id=project.id, task_id=task.id)
        res = client.post(
            url,
            {"is_completed": True},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 200
        task.refresh_from_db()
        assert task.is_completed is True
        assert task.completed_by == student_user
        assert task.completed_at is not None

    def test_student_can_uncomplete_task(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        project.assigned_students.add(student_user)
        task = Task.objects.create(
            project=project,
            title="Done task",
            weight="100.00",
            is_completed=True,
            completed_by=student_user,
            completed_at=timezone.now(),
        )
        url = TOGGLE.format(project_id=project.id, task_id=task.id)
        res = client.post(
            url,
            {"is_completed": False},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 200
        task.refresh_from_db()
        assert task.is_completed is False
        assert task.completed_by is None

    def test_cannot_complete_non_leaf_task(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user, status=Project.Status.IN_PROGRESS)
        project.assigned_students.add(student_user)
        root = make_task(project, "Root")
        make_task(project, "Child", parent=root)   # gives root a child
        url = TOGGLE.format(project_id=project.id, task_id=root.id)
        res = client.post(
            url,
            {"is_completed": True},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 400

    def test_cannot_toggle_on_draft_project(
        self, client, teacher_user, student_user, student_token
    ):
        project = make_project(teacher_user, status=Project.Status.DRAFT)
        project.assigned_students.add(student_user)
        task = make_task(project)
        url = TOGGLE.format(project_id=project.id, task_id=task.id)
        res = client.post(
            url,
            {"is_completed": True},
            content_type="application/json",
            **auth(student_token),
        )
        assert res.status_code == 400
