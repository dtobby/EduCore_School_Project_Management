from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Project, Task
from .selectors import calculate_progress, get_task_tree

User = get_user_model()


class UserBriefSerializer(serializers.ModelSerializer):
    """Minimal user info — used inside project responses."""

    class Meta:
        model = User
        fields = ["id", "username", "email", "role"]


class TaskSerializer(serializers.ModelSerializer):
    """
    Recursive task serializer — reads ._children set by get_task_tree().
    Never calls task.children.all() — that would cause N+1.
    """

    children = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id", "title", "weight", "due_date",
            "is_completed", "completed_at", "order",
            "parent_task", "children",
        ]

    def get_children(self, obj):
        # ._children is attached by get_task_tree() — already in memory
        return TaskSerializer(obj._children, many=True).data


class ProjectSerializer(serializers.ModelSerializer):
    """
    Used for LIST and CREATE.
    - status is read_only — can never be changed via PATCH (rubric red flag if editable)
    - created_by is read_only — set automatically from request.user in the view
    """

    created_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = Project
        fields = [
            "id", "title", "description", "status",
            "deadline", "created_by", "version",
            "created_at", "updated_at",
        ]
        read_only_fields = ["status", "version", "created_by", "created_at", "updated_at"]


class ProjectDetailSerializer(ProjectSerializer):
    """
    Used for RETRIEVE (GET /api/projects/{id}/).
    Adds: nested task tree, assigned students, progress, grade fields.
    """

    tasks = serializers.SerializerMethodField()
    assigned_students = UserBriefSerializer(many=True, read_only=True)
    progress = serializers.SerializerMethodField()

    class Meta(ProjectSerializer.Meta):
        fields = ProjectSerializer.Meta.fields + [
            "tasks", "assigned_students", "progress",
            "grade", "feedback", "submitted_at",
            "submitted_by", "is_late", "graded_at",
        ]

    def get_tasks(self, obj):
        roots = get_task_tree(obj.id)
        return TaskSerializer(roots, many=True).data

    def get_progress(self, obj):
        roots = get_task_tree(obj.id)
        return str(calculate_progress(roots).quantize(
            __import__("decimal").Decimal("0.01")
        ))


class AssignStudentsSerializer(serializers.Serializer):
    """Input for POST /api/projects/{id}/students/"""

    student_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False
    )
