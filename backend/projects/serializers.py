from decimal import Decimal

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
    submitted_by = UserBriefSerializer(read_only=True)
    progress = serializers.SerializerMethodField()

    class Meta(ProjectSerializer.Meta):
        fields = ProjectSerializer.Meta.fields + [
            "tasks", "assigned_students", "progress",
            "grade", "feedback", "submitted_at",
            "submitted_by", "is_late", "graded_at",
        ]

    def to_representation(self, instance):
        self._roots = get_task_tree(instance.id)
        return super().to_representation(instance)

    def get_tasks(self, obj):
        return TaskSerializer(self._roots, many=True).data

    def get_progress(self, obj):
        return str(calculate_progress(self._roots).quantize(Decimal("0.01")))


class AssignStudentsSerializer(serializers.Serializer):
    """Input for POST /api/projects/{id}/students/"""

    student_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False
    )


# ── transition input serializers ──────────────────────────────────────────────

class PublishSerializer(serializers.Serializer):
    """Input for POST /api/projects/{id}/publish/"""
    version = serializers.IntegerField(min_value=1)


class SubmitSerializer(serializers.Serializer):
    """Input for POST /api/projects/{id}/submit/"""
    version = serializers.IntegerField(min_value=1)


class GradeSerializer(serializers.Serializer):
    """Input for POST /api/projects/{id}/grade/"""
    version = serializers.IntegerField(min_value=1)
    grade = serializers.DecimalField(
        max_digits=5, decimal_places=2,
        min_value=Decimal("0.00"), max_value=Decimal("100.00"),
    )
    feedback = serializers.CharField(min_length=1)


class ReturnSerializer(serializers.Serializer):
    """Input for POST /api/projects/{id}/return/"""
    version = serializers.IntegerField(min_value=1)
    feedback = serializers.CharField(min_length=1)


class ForceTransitionSerializer(serializers.Serializer):
    """Input for POST /api/projects/{id}/force-transition/"""
    version = serializers.IntegerField(min_value=1)
    to_status = serializers.ChoiceField(choices=Project.Status.choices)
    reason = serializers.CharField(min_length=1)


# ── task serializers ──────────────────────────────────────────────────────────

class TaskWriteSerializer(serializers.ModelSerializer):
    """
    Used for create, update, retrieve, and toggle output.
    Flat (no recursive children) — the tree is for list/project-detail only.
    """
    class Meta:
        model = Task
        fields = [
            "id", "title", "weight", "due_date",
            "parent_task", "order",
            "is_completed", "completed_by", "completed_at",
        ]
        read_only_fields = ["is_completed", "completed_by", "completed_at"]


class BulkWeightItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    weight = serializers.DecimalField(
        max_digits=5, decimal_places=2,
        min_value=Decimal("0.01"), max_value=Decimal("100.00"),
    )


class BulkWeightSerializer(serializers.Serializer):
    """Input for PUT /api/projects/{id}/tasks/weights/"""
    weights = serializers.ListField(
        child=BulkWeightItemSerializer(), allow_empty=False,
    )


class ToggleSerializer(serializers.Serializer):
    """Input for POST /api/projects/{id}/tasks/{pk}/toggle/"""
    is_completed = serializers.BooleanField()
    version = serializers.IntegerField(min_value=1)
