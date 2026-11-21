import django_filters
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Project, Task
from .permissions import IsAdminRole, IsProjectOwner, IsStudent, IsTeacher
from .selectors import get_projects_for_user, get_task_tree
from .serializers import (
    AssignStudentsSerializer,
    BulkWeightSerializer,
    ForceTransitionSerializer,
    GradeSerializer,
    ProjectDetailSerializer,
    ProjectSerializer,
    PublishSerializer,
    ReturnSerializer,
    SubmitSerializer,
    TaskSerializer,
    TaskWriteSerializer,
    ToggleSerializer,
)
from .services import (
    force_transition,
    grade_project,
    publish_project,
    return_project,
    set_task_weights,
    submit_project,
    validate_task_depth,
)

User = get_user_model()


class ProjectFilter(django_filters.FilterSet):
    deadline_from = django_filters.IsoDateTimeFilter(
        field_name="deadline", lookup_expr="gte"
    )
    deadline_to = django_filters.IsoDateTimeFilter(
        field_name="deadline", lookup_expr="lte"
    )

    class Meta:
        model = Project
        fields = ["status"]


class ProjectViewSet(viewsets.ModelViewSet):
    filterset_class = ProjectFilter
    search_fields = ["title"]
    ordering_fields = ["deadline", "created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            get_projects_for_user(self.request.user)
            .select_related("created_by")
            .prefetch_related("assigned_students")
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProjectDetailSerializer
        return ProjectSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsTeacher()]
        if self.action in [
            "update", "partial_update", "destroy",
            "assign_students", "unassign_student",
            "publish", "grade", "return_for_revision",
        ]:
            return [IsAuthenticated(), IsTeacher(), IsProjectOwner()]
        if self.action == "submit":
            return [IsAuthenticated(), IsStudent()]
        if self.action == "force_transition":
            return [IsAuthenticated(), IsAdminRole()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.status != Project.Status.DRAFT:
            raise ValidationError(
                {"code": "not_editable",
                 "detail": "Project can only be edited while in DRAFT status."}
            )
        serializer.save()

    def perform_destroy(self, instance):
        if instance.status != Project.Status.DRAFT:
            raise ValidationError(
                {"code": "not_editable",
                 "detail": "Project can only be deleted while in DRAFT status."}
            )
        instance.delete()

    @action(detail=True, methods=["post"], url_path="students")
    def assign_students(self, request, pk=None):
        """POST /api/projects/{id}/students/ — assign students to a project."""
        project = self.get_object()
        serializer = AssignStudentsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        students = User.objects.filter(
            id__in=serializer.validated_data["student_ids"],
            role="STUDENT",
        )
        project.assigned_students.add(*students)
        return Response(ProjectDetailSerializer(project).data)

    @action(
        detail=True, methods=["delete"],
        url_path="students/(?P<student_id>[^/.]+)",
    )
    def unassign_student(self, request, pk=None, student_id=None):
        """DELETE /api/projects/{id}/students/{student_id}/ — remove a student."""
        project = self.get_object()
        student = get_object_or_404(User, id=student_id, role="STUDENT")
        project.assigned_students.remove(student)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── state machine transitions ─────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="publish")
    def publish(self, request, pk=None):
        """POST /api/projects/{id}/publish/ — DRAFT → IN_PROGRESS (teacher only)."""
        self.get_object()   # permission + 404 check
        s = PublishSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        project = publish_project(pk, request.user, s.validated_data["version"])
        return Response(ProjectDetailSerializer(project).data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        """POST /api/projects/{id}/submit/ — IN_PROGRESS → SUBMITTED (assigned student only)."""
        self.get_object()   # permission + 404 check
        s = SubmitSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        project = submit_project(pk, request.user, s.validated_data["version"])
        return Response(ProjectDetailSerializer(project).data)

    @action(detail=True, methods=["post"], url_path="grade")
    def grade(self, request, pk=None):
        """POST /api/projects/{id}/grade/ — SUBMITTED → GRADED (owning teacher only)."""
        self.get_object()   # permission + 404 check
        s = GradeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        project = grade_project(pk, request.user, d["version"], d["grade"], d["feedback"])
        return Response(ProjectDetailSerializer(project).data)

    @action(detail=True, methods=["post"], url_path="return")
    def return_for_revision(self, request, pk=None):
        """POST /api/projects/{id}/return/ — SUBMITTED → IN_PROGRESS (owning teacher only)."""
        self.get_object()   # permission + 404 check
        s = ReturnSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        project = return_project(pk, request.user, d["version"], d["feedback"])
        return Response(ProjectDetailSerializer(project).data)

    @action(detail=True, methods=["post"], url_path="force-transition")
    def force_transition(self, request, pk=None):
        """POST /api/projects/{id}/force-transition/ — admin override, any → any."""
        self.get_object()   # permission + 404 check
        s = ForceTransitionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        project = force_transition(pk, request.user, d["to_status"], d["reason"], d["version"])
        return Response(ProjectDetailSerializer(project).data)


# ── Task CRUD ─────────────────────────────────────────────────────────────────

class TaskViewSet(viewsets.GenericViewSet):
    """
    Nested under projects: /api/projects/{project_pk}/tasks/
    Uses project scoping — the user can only reach tasks of projects they can see.
    """

    def _get_project(self):
        """
        Fetch the parent project, applying the same user-scoped queryset as
        ProjectViewSet.  A student can't reach tasks of an unassigned project.
        """
        return get_object_or_404(
            get_projects_for_user(self.request.user),
            pk=self.kwargs["project_pk"],
        )

    def get_queryset(self):
        return Task.objects.filter(project__pk=self.kwargs["project_pk"])

    def get_permissions(self):
        if self.action in ["create", "partial_update", "destroy", "bulk_weights"]:
            return [IsAuthenticated(), IsTeacher()]
        return [IsAuthenticated()]

    # ── list (returns tree, not flat queryset) ────────────────────────────────

    def list(self, request, project_pk=None):
        """GET /api/projects/{id}/tasks/ — returns nested task tree."""
        project = self._get_project()
        roots = get_task_tree(project.id)
        return Response(TaskSerializer(roots, many=True).data)

    # ── create ────────────────────────────────────────────────────────────────

    def create(self, request, project_pk=None):
        """POST /api/projects/{id}/tasks/ — teacher only, project must be DRAFT."""
        project = self._get_project()
        if project.status != Project.Status.DRAFT:
            raise ValidationError("Tasks can only be added to DRAFT projects.")
        # Check the teacher owns this project
        if project.created_by != request.user:
            raise ValidationError("You do not own this project.")

        s = TaskWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        parent_task = s.validated_data.get("parent_task")
        if parent_task:
            if parent_task.project_id != project.id:
                raise ValidationError("Parent task must belong to the same project.")
            validate_task_depth(parent_task)

        task = s.save(project=project)
        return Response(TaskWriteSerializer(task).data, status=status.HTTP_201_CREATED)

    # ── retrieve ──────────────────────────────────────────────────────────────

    def retrieve(self, request, project_pk=None, pk=None):
        """GET /api/projects/{id}/tasks/{pk}/ — flat task (no nested children)."""
        self._get_project()   # 404 if user can't see the project
        task = get_object_or_404(Task, pk=pk, project__pk=project_pk)
        return Response(TaskWriteSerializer(task).data)

    # ── partial_update ────────────────────────────────────────────────────────

    def partial_update(self, request, project_pk=None, pk=None):
        """PATCH /api/projects/{id}/tasks/{pk}/ — teacher only, project must be DRAFT."""
        project = self._get_project()
        if project.status != Project.Status.DRAFT:
            raise ValidationError("Tasks can only be edited on DRAFT projects.")
        if project.created_by != request.user:
            raise ValidationError("You do not own this project.")

        task = get_object_or_404(Task, pk=pk, project=project)
        s = TaskWriteSerializer(task, data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        parent_task = s.validated_data.get("parent_task")
        if parent_task:
            if parent_task.project_id != project.id:
                raise ValidationError("Parent task must belong to the same project.")
            if parent_task.pk == task.pk:
                raise ValidationError("A task cannot be its own parent.")
            validate_task_depth(parent_task)

        s.save()
        return Response(TaskWriteSerializer(task).data)

    # ── destroy ───────────────────────────────────────────────────────────────

    def destroy(self, request, project_pk=None, pk=None):
        """DELETE /api/projects/{id}/tasks/{pk}/ — teacher only, project must be DRAFT."""
        project = self._get_project()
        if project.status != Project.Status.DRAFT:
            raise ValidationError("Tasks can only be deleted from DRAFT projects.")
        if project.created_by != request.user:
            raise ValidationError("You do not own this project.")
        task = get_object_or_404(Task, pk=pk, project=project)
        task.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── bulk weights ──────────────────────────────────────────────────────────

    def bulk_weights(self, request, project_pk=None):
        """PUT /api/projects/{id}/tasks/weights/ — atomically set multiple weights."""
        project = self._get_project()
        if project.created_by != request.user:
            raise ValidationError("You do not own this project.")
        s = BulkWeightSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tasks = set_task_weights(project.id, s.validated_data["weights"])
        return Response(TaskWriteSerializer(tasks, many=True).data)

    # ── toggle completion ─────────────────────────────────────────────────────

    def toggle_completion(self, request, project_pk=None, pk=None):
        """POST /api/projects/{id}/tasks/{pk}/toggle/ — mark task complete/incomplete."""
        project = self._get_project()
        if project.status != Project.Status.IN_PROGRESS:
            raise ValidationError("Task completion only allowed on IN_PROGRESS projects.")

        task = get_object_or_404(Task, pk=pk, project=project)

        if task.children.exists():
            raise ValidationError("Only leaf tasks (no subtasks) can be marked complete.")

        s = ToggleSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        task.is_completed = s.validated_data["is_completed"]
        if task.is_completed:
            task.completed_by = request.user
            task.completed_at = timezone.now()
        else:
            task.completed_by = None
            task.completed_at = None
        task.save(update_fields=["is_completed", "completed_by", "completed_at"])
        return Response(TaskWriteSerializer(task).data)
