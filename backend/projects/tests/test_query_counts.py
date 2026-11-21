"""
Query count tests — proves no N+1 queries exist. NFR-01.

The key insight: a fixed number of queries regardless of how many projects/tasks
exist proves the code uses JOINs + prefetch instead of one query per object.

Run: docker compose exec backend pytest projects/tests/test_query_counts.py -v
"""
import pytest
from datetime import timedelta

from django.utils import timezone

from projects.models import Project, Task


def auth(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def make_project(teacher, status=Project.Status.DRAFT, days=30):
    return Project.objects.create(
        title="QC Project",
        created_by=teacher,
        deadline=timezone.now() + timedelta(days=days),
        status=status,
    )


# ── project list ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProjectListQueryCount:
    def test_query_count_is_constant_for_project_list(
        self, client, teacher_user, teacher_token, django_assert_num_queries
    ):
        """
        GET /api/projects/ must run a fixed number of queries no matter how many
        projects exist. Currently: 4 (auth + COUNT + SELECT w/ join + prefetch M2M).
        """
        for i in range(5):
            p = make_project(teacher_user)
            Task.objects.create(project=p, title=f"Task {i}", weight="100.00")

        with django_assert_num_queries(4):
            client.get("/api/projects/", **auth(teacher_token))

    def test_adding_more_projects_does_not_add_queries(
        self, client, teacher_user, teacher_token, django_assert_num_queries
    ):
        """Adding 10 more projects must not change the query count — no N+1."""
        for i in range(10):
            make_project(teacher_user)

        with django_assert_num_queries(4):
            client.get("/api/projects/", **auth(teacher_token))


# ── project detail ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProjectDetailQueryCount:
    def test_detail_with_deep_task_tree_runs_fixed_queries(
        self, client, teacher_user, teacher_token, django_assert_num_queries
    ):
        """
        GET /api/projects/{id}/ with a 2-level task tree must not issue one query
        per task. Currently: 4 (auth + project+JOIN + prefetch M2M + get_task_tree).
        """
        project = make_project(teacher_user)
        root = Task.objects.create(project=project, title="Root", weight="100.00")
        for i in range(5):
            Task.objects.create(
                project=project, title=f"Child {i}",
                weight="20.00", parent_task=root,
            )

        url = f"/api/projects/{project.id}/"
        with django_assert_num_queries(4):
            client.get(url, **auth(teacher_token))


# ── schedule ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestScheduleQueryCount:
    def test_teacher_schedule_always_runs_three_queries(
        self, client, teacher_user, teacher_token, django_assert_num_queries
    ):
        """
        GET /api/schedule/ for a teacher must always run 3 queries:
        auth + projects-in-date-range + submitted-projects-queue.
        """
        now = timezone.now()
        for i in range(5):
            Project.objects.create(
                title=f"P{i}",
                created_by=teacher_user,
                deadline=now + timedelta(days=i + 1),
                status=Project.Status.IN_PROGRESS,
            )

        with django_assert_num_queries(3):
            client.get(
                f"/api/schedule/?from={now.date()}&to={(now + timedelta(days=30)).date()}",
                **auth(teacher_token),
            )
