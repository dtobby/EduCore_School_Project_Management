from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from projects.models import Project, ProjectStatusLog, Task

User = get_user_model()

_USERS = [
    {"username": "admin1",    "password": "admin123",   "role": "ADMIN",   "email": "admin1@educore.test",   "is_staff": True,  "is_superuser": True},
    {"username": "teacher1",  "password": "teacher123", "role": "TEACHER", "email": "teacher1@educore.test", "is_staff": False, "is_superuser": False},
    {"username": "student1",  "password": "student123", "role": "STUDENT", "email": "student1@educore.test", "is_staff": False, "is_superuser": False},
    {"username": "student2",  "password": "student123", "role": "STUDENT", "email": "student2@educore.test", "is_staff": False, "is_superuser": False},
]


def _log(project, from_status, to_status, user, reason="", is_forced=False):
    ProjectStatusLog.objects.create(
        project=project,
        from_status=from_status,
        to_status=to_status,
        changed_by=user,
        reason=reason,
        is_forced=is_forced,
    )


class Command(BaseCommand):
    help = "Seed the database with demo data (idempotent — safe to run multiple times)"

    def handle(self, *args, **options):
        self.stdout.write("Seeding school data …")
        now = timezone.now()

        # ── users ─────────────────────────────────────────────────────────────
        users = {}
        for spec in _USERS:
            user, created = User.objects.get_or_create(
                username=spec["username"],
                defaults={
                    "email": spec["email"],
                    "role": spec["role"],
                    "is_staff": spec["is_staff"],
                    "is_superuser": spec["is_superuser"],
                },
            )
            if created:
                user.set_password(spec["password"])
                user.save(update_fields=["password"])
                self.stdout.write(f"  + user  {user.username} ({user.role})")
            users[spec["username"]] = user

        teacher = users["teacher1"]
        s1 = users["student1"]
        s2 = users["student2"]

        # ── Project 1 — DRAFT ─────────────────────────────────────────────────
        p1, created = Project.objects.get_or_create(
            title="[DEMO] Science Fair",
            defaults={
                "created_by": teacher,
                "description": "Annual school science fair — groups design and test a hypothesis.",
                "deadline": now + timezone.timedelta(days=30),
                "status": Project.Status.DRAFT,
                "version": 1,
            },
        )
        if created:
            Task.objects.create(project=p1, title="Design experiment", weight="60.00", order=1)
            Task.objects.create(project=p1, title="Build model",       weight="40.00", order=2)
            self.stdout.write(f"  + project {p1.title} [{p1.status}]")

        # ── Project 2 — IN_PROGRESS ───────────────────────────────────────────
        p2, created = Project.objects.get_or_create(
            title="[DEMO] History Essay",
            defaults={
                "created_by": teacher,
                "description": "Research essay on the Industrial Revolution.",
                "deadline": now + timezone.timedelta(days=14),
                "status": Project.Status.IN_PROGRESS,
                "version": 2,
            },
        )
        if created:
            root = Task.objects.create(project=p2, title="Write essay", weight="100.00", order=1)
            outline = Task.objects.create(
                project=p2, title="Outline", weight="30.00", order=1, parent_task=root,
                is_completed=True, completed_by=s1, completed_at=now - timezone.timedelta(hours=6),
            )
            Task.objects.create(project=p2, title="First draft", weight="70.00", order=2, parent_task=root)
            p2.assigned_students.add(s1, s2)
            _log(p2, Project.Status.DRAFT, Project.Status.IN_PROGRESS, teacher)
            self.stdout.write(f"  + project {p2.title} [{p2.status}]")

        # ── Project 3 — SUBMITTED ─────────────────────────────────────────────
        p3, created = Project.objects.get_or_create(
            title="[DEMO] Math Investigation",
            defaults={
                "created_by": teacher,
                "description": "Investigate patterns in prime numbers.",
                "deadline": now + timezone.timedelta(days=7),
                "status": Project.Status.SUBMITTED,
                "submitted_at": now - timezone.timedelta(hours=2),
                "submitted_by": s1,
                "is_late": False,
                "version": 3,
            },
        )
        if created:
            Task.objects.create(
                project=p3, title="Collect data", weight="50.00", order=1,
                is_completed=True, completed_by=s1, completed_at=now - timezone.timedelta(hours=5),
            )
            Task.objects.create(
                project=p3, title="Analyse patterns", weight="50.00", order=2,
                is_completed=True, completed_by=s2, completed_at=now - timezone.timedelta(hours=3),
            )
            p3.assigned_students.add(s1, s2)
            _log(p3, Project.Status.DRAFT,       Project.Status.IN_PROGRESS, teacher)
            _log(p3, Project.Status.IN_PROGRESS, Project.Status.SUBMITTED,   s1)
            self.stdout.write(f"  + project {p3.title} [{p3.status}]")

        # ── Project 4 — GRADED ────────────────────────────────────────────────
        p4, created = Project.objects.get_or_create(
            title="[DEMO] Art Portfolio",
            defaults={
                "created_by": teacher,
                "description": "Create a digital art portfolio with at least five pieces.",
                "deadline": now - timezone.timedelta(days=10),
                "status": Project.Status.GRADED,
                "submitted_at": now - timezone.timedelta(days=12),
                "submitted_by": s2,
                "is_late": False,
                "grade": "88.50",
                "feedback": "Excellent creativity and attention to detail. Strong composition throughout.",
                "graded_at": now - timezone.timedelta(days=1),
                "version": 4,
            },
        )
        if created:
            Task.objects.create(
                project=p4, title="Concept sketches", weight="40.00", order=1,
                is_completed=True, completed_by=s2, completed_at=now - timezone.timedelta(days=14),
            )
            Task.objects.create(
                project=p4, title="Digital artwork", weight="60.00", order=2,
                is_completed=True, completed_by=s2, completed_at=now - timezone.timedelta(days=13),
            )
            p4.assigned_students.add(s2)
            _log(p4, Project.Status.DRAFT,       Project.Status.IN_PROGRESS, teacher)
            _log(p4, Project.Status.IN_PROGRESS, Project.Status.SUBMITTED,   s2)
            _log(p4, Project.Status.SUBMITTED,   Project.Status.GRADED,      teacher)
            self.stdout.write(f"  + project {p4.title} [{p4.status}]")

        self.stdout.write(self.style.SUCCESS(
            "\nDone. Demo credentials:\n"
            "  admin1   / admin123    (ADMIN)\n"
            "  teacher1 / teacher123  (TEACHER)\n"
            "  student1 / student123  (STUDENT)\n"
            "  student2 / student123  (STUDENT)\n"
        ))
