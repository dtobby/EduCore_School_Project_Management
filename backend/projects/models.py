from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class Project(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        SUBMITTED = "SUBMITTED", "Submitted"
        GRADED = "GRADED", "Graded"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    deadline = models.DateTimeField(db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_projects",
        limit_choices_to={"role": "TEACHER"},
    )
    assigned_students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="assigned_projects",
        blank=True,
        limit_choices_to={"role": "STUDENT"},
    )

    grade = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    feedback = models.TextField(blank=True)

    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submitted_projects",
    )
    is_late = models.BooleanField(default=False)
    graded_at = models.DateTimeField(null=True, blank=True)

    version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(grade__isnull=True)
                | (Q(grade__gte=Decimal("0.00")) & Q(grade__lte=Decimal("100.00"))),
                name="project_grade_between_0_and_100",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.status})"


class Task(models.Model):
    MAX_DEPTH = 3

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    parent_task = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    title = models.CharField(max_length=200)
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.01")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    due_date = models.DateTimeField(null=True, blank=True)

    is_completed = models.BooleanField(default=False)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="completed_tasks",
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["project", "parent_task"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(weight__gte=Decimal("0.01")) & Q(weight__lte=Decimal("100.00")),
                name="task_weight_between_0_01_and_100",
            ),
            models.CheckConstraint(
                condition=~Q(parent_task=F("id")),
                name="task_cannot_be_its_own_parent",
            ),
        ]

    def __str__(self):
        return self.title


class ProjectStatusLog(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="status_logs",
    )
    from_status = models.CharField(max_length=20, choices=Project.Status.choices)
    to_status = models.CharField(max_length=20, choices=Project.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="status_changes",
    )
    reason = models.TextField(blank=True)
    is_forced = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(is_forced=False) | ~Q(reason=""),
                name="forced_transition_requires_reason",
            ),
        ]

    def __str__(self):
        return f"{self.project_id}: {self.from_status} -> {self.to_status}"
