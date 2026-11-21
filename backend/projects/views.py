import django_filters
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
    toggle_task_completion,
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
        self._get_project()   # 404 if user can't see this project
        s = ToggleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        task = toggle_task_completion(
            project_id=project_pk,
            task_id=pk,
            user=request.user,
            is_completed=s.validated_data["is_completed"],
            version=s.validated_data["version"],
        )
        return Response(TaskWriteSerializer(task).data)


# ── Schedule ──────────────────────────────────────────────────────────────────

class ScheduleView(APIView):
    """
    GET /api/schedule/?from=&to=
    Returns a flat, date-sorted list of upcoming events for the requesting user.
    Default range: now → now + 30 days.

    Student: IN_PROGRESS project deadlines + incomplete task due dates (assigned projects).
    Teacher: project deadlines (in range) + ALL SUBMITTED projects (submission queue).
    Admin:   empty list.

    2 DB queries per role — no N+1.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        from_dt = self._parse_dt(request.query_params.get("from"), now)
        to_dt = self._parse_dt(request.query_params.get("to"), now + timedelta(days=30))

        user = request.user
        if user.role == "STUDENT":
            events = self._student_events(user, from_dt, to_dt)
        elif user.role == "TEACHER":
            events = self._teacher_events(user, from_dt, to_dt)
        else:
            events = []

        events.sort(key=lambda e: e["date"])
        return Response(events)

    @staticmethod
    def _parse_dt(value, default):
        if not value:
            return default
        # Try full datetime first (e.g. 2026-11-20T10:00:00), then date-only (2026-11-20)
        dt = parse_datetime(value)
        if dt is None:
            d = parse_date(value)
            if d is not None:
                dt = timezone.make_aware(datetime(d.year, d.month, d.day))
        if dt is None:
            raise ValidationError(f"Invalid date '{value}'. Use ISO 8601, e.g. 2026-11-20.")
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt

    @staticmethod
    def _student_events(user, from_dt, to_dt):
        events = []
        # Query 1: IN_PROGRESS project deadlines assigned to this student
        for p in Project.objects.filter(
            assigned_students=user,
            status=Project.Status.IN_PROGRESS,
            deadline__range=(from_dt, to_dt),
        ):
            events.append({
                "type": "deadline",
                "date": p.deadline.isoformat(),
                "project_id": p.id,
                "title": p.title,
            })
        # Query 2: incomplete tasks with due_date in range (student's IN_PROGRESS projects)
        for t in Task.objects.filter(
            project__assigned_students=user,
            project__status=Project.Status.IN_PROGRESS,
            is_completed=False,
            due_date__range=(from_dt, to_dt),
        ):
            events.append({
                "type": "task_due",
                "date": t.due_date.isoformat(),
                "project_id": t.project_id,
                "title": t.title,
            })
        return events

    @staticmethod
    def _teacher_events(user, from_dt, to_dt):
        events = []
        # Query 1: deadlines of the teacher's own projects in range
        for p in Project.objects.filter(
            created_by=user,
            deadline__range=(from_dt, to_dt),
        ):
            events.append({
                "type": "deadline",
                "date": p.deadline.isoformat(),
                "project_id": p.id,
                "title": p.title,
            })
        # Query 2: submission queue — ALL submitted projects, not date-filtered
        # They're a pending work inbox; filtering by date would hide old submissions.
        for p in Project.objects.filter(
            created_by=user,
            status=Project.Status.SUBMITTED,
        ).order_by("submitted_at"):
            events.append({
                "type": "submission",
                "date": p.submitted_at.isoformat(),
                "project_id": p.id,
                "title": p.title,
            })
        return events


# Admin stats

class AdminStatsView(APIView):
    """
    GET /api/admin/stats/ — admin only.
    Returns user counts by role, project counts by status, average grade,
    and the number of overdue IN_PROGRESS projects.

    3 DB queries total — always, regardless of how much data exists:
      1. user counts by role
      2. project counts by status
      3. one aggregate: average grade (GRADED only) + overdue count (conditional)
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        now = timezone.now()

        # Query 1 — user counts grouped by role
        role_rows = User.objects.values("role").annotate(n=Count("id"))
        users = {row["role"]: row["n"] for row in role_rows}
        for role in ("ADMIN", "TEACHER", "STUDENT"):
            users.setdefault(role, 0)

        # Query 2 — project counts grouped by status
        status_rows = Project.objects.values("status").annotate(n=Count("id"))
        projects = {row["status"]: row["n"] for row in status_rows}
        for s in Project.Status.values:
            projects.setdefault(s, 0)

        # Query 3 — single aggregate: avg grade + overdue count
        # filter= inside Count/Avg is conditional aggregation (SQL CASE WHEN ... END).
        # One query no matter how many rows exist.
        agg = Project.objects.aggregate(
            average_grade=Avg("grade", filter=Q(status=Project.Status.GRADED)),
            overdue_projects=Count(
                "id",
                filter=Q(status=Project.Status.IN_PROGRESS, deadline__lt=now),
            ),
        )

        return Response({
            "users": users,
            "projects": projects,
            "average_grade": agg["average_grade"],
            "overdue_projects": agg["overdue_projects"],
        })
