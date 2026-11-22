from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.exceptions import PreconditionError, StaleDataError
from .models import Project, ProjectStatusLog, Task
from .selectors import get_task_tree


# ── private helpers 

def _validate_sibling_weights(tasks, errors):
    """Each group of sibling tasks must sum to exactly 100.00."""
    total = sum(t.weight for t in tasks)
    if total != Decimal("100.00"):
        titles = [t.title for t in tasks]
        errors.append(
            f"Tasks {titles} weights sum to {total:.2f}, must be exactly 100.00."
        )
    for task in tasks:
        if task._children:
            _validate_sibling_weights(task._children, errors)


def _check_publish_preconditions(project):
    """Raise PreconditionError if the project is not ready to publish."""
    errors = []

    if not project.assigned_students.exists():
        errors.append("At least one student must be assigned before publishing.")

    if project.deadline <= timezone.now():
        errors.append("Project deadline must be in the future.")

    roots = get_task_tree(project.id)
    if not roots:
        errors.append("At least one task must be added before publishing.")
    else:
        _validate_sibling_weights(roots, errors)

    if errors:
        raise PreconditionError(
            detail=errors[0] if len(errors) == 1 else "; ".join(errors)
        )

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


# ── public transitions 

@transaction.atomic
def publish_project(project_id, user, version):
    """DRAFT → IN_PROGRESS.  Called by the owning teacher."""
    project = _acquire(project_id)
    _check_version(project, version)

    if project.status != Project.Status.DRAFT:
        raise ValidationError(
            f"Cannot publish a project with status '{project.status}'."
        )

    _check_publish_preconditions(project)

    from_status = project.status
    project.status = Project.Status.IN_PROGRESS
    project.version += 1
    project.save(update_fields=["status", "version", "updated_at"])
    _log(project, from_status, Project.Status.IN_PROGRESS, user)
    return project


def _check_all_leaves_complete(project_id):
    """Raise PreconditionError if any leaf task is not completed. FR-09."""
    roots = get_task_tree(project_id)
    if not roots:
        return  

    incomplete = []

    def _walk(tasks):
        for task in tasks:
            if task._children:
                _walk(task._children)
            elif not task.is_completed:
                incomplete.append(task.title)

    _walk(roots)

    if incomplete:
        n = len(incomplete)
        raise PreconditionError(
            f"{n} leaf task{'s' if n > 1 else ''} must be completed before submitting."
        )


@transaction.atomic
def submit_project(project_id, user, version):
    """IN_PROGRESS → SUBMITTED.  Called by an assigned student."""
    project = _acquire(project_id)
    _check_version(project, version)

    if project.status != Project.Status.IN_PROGRESS:
        raise ValidationError(
            f"Cannot submit a project with status '{project.status}'."
        )

    _check_all_leaves_complete(project.id)

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


# ── task helpers 

def get_task_depth(task):
    """
    Return the 1-based depth of a task in its project's tree.
    Root tasks (parent_task=None) are depth 1.  Walks up via DB queries;
    at most MAX_DEPTH−1 extra queries (i.e. 2 extra at most).
    """
    depth = 1
    current_id = task.parent_task_id
    while current_id is not None:
        depth += 1
        current_id = (
            Task.objects
            .values_list("parent_task_id", flat=True)
            .get(id=current_id)
        )
    return depth


def validate_task_depth(parent_task):
    """Raise ValidationError if adding a child to parent_task would exceed MAX_DEPTH."""
    parent_depth = get_task_depth(parent_task)
    if parent_depth >= Task.MAX_DEPTH:
        raise ValidationError(
            f"Maximum task depth ({Task.MAX_DEPTH}) exceeded."
        )


@transaction.atomic
def toggle_task_completion(project_id, task_id, user, is_completed, version):
    """
    Mark a leaf task complete or incomplete.  FR-10.
    Locks the project row so a concurrent submit cannot see a half-toggled state.
    """
    project = _acquire(project_id)
    _check_version(project, version)

    if project.status != Project.Status.IN_PROGRESS:
        raise ValidationError("Task completion only allowed on IN_PROGRESS projects.")

    try:
        task = Task.objects.get(id=task_id, project=project)
    except Task.DoesNotExist:
        raise ValidationError("Task not found.")

    if task.children.exists():
        raise ValidationError("Only leaf tasks (no subtasks) can be marked complete.")

    task.is_completed = is_completed
    if is_completed:
        task.completed_by = user
        task.completed_at = timezone.now()
    else:
        task.completed_by = None
        task.completed_at = None
    task.save(update_fields=["is_completed", "completed_by", "completed_at"])

    project.version += 1
    project.save(update_fields=["version", "updated_at"])

    return task


@transaction.atomic
def set_task_weights(project_id, weight_items):
    """
    Bulk-update task weights atomically.
    weight_items: list of {"id": int, "weight": Decimal}
    All task IDs must belong to this project; raises ValidationError if any don't.
    """
    task_ids = [item["id"] for item in weight_items]
    found = set(
        Task.objects.filter(project_id=project_id, id__in=task_ids)
        .values_list("id", flat=True)
    )
    missing = set(task_ids) - found
    if missing:
        raise ValidationError(
            f"Task IDs {sorted(missing)} do not belong to this project."
        )
    for item in weight_items:
        Task.objects.filter(id=item["id"]).update(weight=item["weight"])
    return list(Task.objects.filter(project_id=project_id).order_by("order", "id"))
