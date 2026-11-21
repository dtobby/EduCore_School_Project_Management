import django_filters
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Project
from .permissions import IsAdminRole, IsProjectOwner, IsStudent, IsTeacher
from .selectors import get_projects_for_user
from .serializers import (
    AssignStudentsSerializer,
    ForceTransitionSerializer,
    GradeSerializer,
    ProjectDetailSerializer,
    ProjectSerializer,
    PublishSerializer,
    ReturnSerializer,
    SubmitSerializer,
)
from .services import (
    force_transition,
    grade_project,
    publish_project,
    return_project,
    submit_project,
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
