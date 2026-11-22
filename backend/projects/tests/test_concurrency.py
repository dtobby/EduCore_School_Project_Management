"""
Concurrency test — proves pessimistic lock prevents double-submit. Section 7 Testing.

Two students hit submit at the same millisecond.  select_for_update() inside
submit_project() means one gets the row lock, the other waits, then sees the
already-incremented version and returns 409 stale_data.

Run: docker compose exec backend pytest projects/tests/test_concurrency.py -v
"""
import threading

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from projects.models import Project

User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_simultaneous_submits_one_succeeds_one_conflicts():
    """
    Two students submit the same project simultaneously.
    Exactly one must get 200; the other must get 409 stale_data.
    """
    teacher = User.objects.create_user(username="t_cc", password="t123", role="TEACHER")
    s1 = User.objects.create_user(username="s_cc1", password="s123", role="STUDENT")
    s2 = User.objects.create_user(username="s_cc2", password="s123", role="STUDENT")

    project = Project.objects.create(
        title="Race Project",
        created_by=teacher,
        deadline=timezone.now() + timezone.timedelta(days=10),
        status=Project.Status.IN_PROGRESS,
        version=1,
    )
    project.assigned_students.add(s1, s2)

    barrier = threading.Barrier(2, timeout=10)
    results = []
    lock = threading.Lock()

    def submit_as(username, password):
        c = Client()
        token_res = c.post(
            "/api/auth/token/",
            {"username": username, "password": password},
            content_type="application/json",
        )
        token = token_res.json()["access"]

        barrier.wait()  # both threads reach here before either fires the submit

        res = c.post(
            f"/api/projects/{project.id}/submit/",
            {"version": 1},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        with lock:
            results.append(res.status_code)

    t1 = threading.Thread(target=submit_as, args=["s_cc1", "s123"])
    t2 = threading.Thread(target=submit_as, args=["s_cc2", "s123"])
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(results) == [200, 409], (
        f"Expected one 200 and one 409, got {sorted(results)}"
    )
