from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.exceptions import StaleDataError
from .models import Project, ProjectStatusLog


# ── private helpers ───────────────────────────────────────────────────────────

def _acquire(project_id):
    """
    Fetch the project with a row-level lock (SELECT FOR UPDATE).
    Must be called inside transaction.atomic().
    If two requests arrive simultaneously, the second one waits here until
    the first transaction commits — then it sees the updated status.
    """
    try:
        return Project.objects.select_for_update().get(id=project_id)
    except Project.DoesNotExist:
        raise ValidationError("Project not found.")


def _check_version(project, client_version):
    """
    Optimistic locking check.
    The client sends the version it last read.  If someone else changed the
    project between the client's GET and this POST, the versions diverge → 409.
    """
    if project.version != client_version:
        raise StaleDataError()


def _log(project, from_status, to_status, user, reason="", is_forced=False):
    ProjectStatusLog.objects.create(
        project=project,
        from_status=from_status,
        to_status=to_status,
        changed_by=user,
        reason=reason,
        is_forced=is_forced,
    )


# ── public transitions ────────────────────────────────────────────────────────

@transaction.atomic
def publish_project(project_id, user, version):
    """DRAFT → IN_PROGRESS.  Called by the owning teacher."""
    project = _acquire(project_id)
    _check_version(project, version)

    if project.status != Project.Status.DRAFT:
        raise ValidationError(
            f"Cannot publish a project with status '{project.status}'."
        )

    from_status = project.status
    project.status = Project.Status.IN_PROGRESS
    project.version += 1
    project.save(update_fields=["status", "version", "updated_at"])
    _log(project, from_status, Project.Status.IN_PROGRESS, user)
    return project


@transaction.atomic
def submit_project(project_id, user, version):
    """IN_PROGRESS → SUBMITTED.  Called by an assigned student."""
    project = _acquire(project_id)
    _check_version(project, version)

    if project.status != Project.Status.IN_PROGRESS:
        raise ValidationError(
            f"Cannot submit a project with status '{project.status}'."
        )

    from_status = project.status
    now = timezone.now()
    project.status = Project.Status.SUBMITTED
    project.submitted_at = now
    project.submitted_by = user
    project.is_late = now > project.deadline
    project.version += 1
    project.save(update_fields=[
        "status", "submitted_at", "submitted_by", "is_late", "version", "updated_at",
    ])
    _log(project, from_status, Project.Status.SUBMITTED, user)
    return project


@transaction.atomic
def grade_project(project_id, user, version, grade, feedback):
    """SUBMITTED → GRADED.  Called by the owning teacher."""
    project = _acquire(project_id)
    _check_version(project, version)

    if project.status != Project.Status.SUBMITTED:
        raise ValidationError(
            f"Cannot grade a project with status '{project.status}'."
        )

    from_status = project.status
    project.status = Project.Status.GRADED
    project.grade = grade
    project.feedback = feedback
    project.graded_at = timezone.now()
    project.version += 1
    project.save(update_fields=[
        "status", "grade", "feedback", "graded_at", "version", "updated_at",
    ])
    _log(project, from_status, Project.Status.GRADED, user)
    return project


@transaction.atomic
def return_project(project_id, user, version, feedback):
    """SUBMITTED → IN_PROGRESS (return for revision).  Called by owning teacher."""
    project = _acquire(project_id)
    _check_version(project, version)

    if project.status != Project.Status.SUBMITTED:
        raise ValidationError(
            f"Cannot return a project with status '{project.status}'."
        )

    from_status = project.status
    project.status = Project.Status.IN_PROGRESS
    project.feedback = feedback
    project.version += 1
    project.save(update_fields=["status", "feedback", "version", "updated_at"])
    _log(project, from_status, Project.Status.IN_PROGRESS, user)
    return project


@transaction.atomic
def force_transition(project_id, user, to_status, reason, version):
    """Any → any.  Admin-only override.  Always logged with is_forced=True."""
    project = _acquire(project_id)
    _check_version(project, version)

    if project.status == to_status:
        raise ValidationError(f"Project is already '{to_status}'.")

    from_status = project.status
    project.status = to_status
    project.version += 1
    project.save(update_fields=["status", "version", "updated_at"])
    _log(project, from_status, to_status, user, reason=reason, is_forced=True)
    return project
