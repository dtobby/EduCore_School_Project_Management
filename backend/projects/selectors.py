from .models import Project, Task


def get_projects_for_user(user):
    """
    Returns a queryset scoped to what this user is allowed to see.

    Admin   → all projects
    Teacher → only projects they created
    Student → only projects they are assigned to

    Views call this in get_queryset(). DRF's get_object() filters through
    get_queryset() first, so an out-of-scope object raises 404 automatically.
    """
    if user.is_admin_role:
        return Project.objects.all()
    elif user.is_teacher:
        return Project.objects.filter(created_by=user)
    else:
        return Project.objects.filter(assigned_students=user)


def get_task_tree(project_id):
    """
    Load all tasks for a project in ONE query, then assemble the tree in Python.

    This is the core NFR-01 pattern — no N+1 queries.

    Returns a list of root tasks. Each task has a ._children attribute
    (list of child tasks). Children also have ._children (grandchildren), etc.

    The serializer reads ._children instead of calling task.children.all()
    which would hit the database once per task.
    """
    tasks = list(
        Task.objects.filter(project_id=project_id).order_by("order", "id")
    )

    by_parent = {}
    for task in tasks:
        by_parent.setdefault(task.parent_task_id, []).append(task)

    for task in tasks:
        task._children = by_parent.get(task.id, [])

    return by_parent.get(None, [])
