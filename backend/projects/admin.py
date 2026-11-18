from django.contrib import admin

from .models import Project, ProjectStatusLog, Task


class TaskInline(admin.TabularInline):
    model = Task
    extra = 0
    fields = ("title", "parent_task", "weight", "order", "is_completed")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "created_by", "deadline", "grade", "version")
    list_filter = ("status",)
    search_fields = ("title",)
    filter_horizontal = ("assigned_students",)
    readonly_fields = ("status", "version", "created_at", "updated_at")
    inlines = [TaskInline]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "parent_task", "weight", "is_completed")
    list_filter = ("is_completed",)


@admin.register(ProjectStatusLog)
class ProjectStatusLogAdmin(admin.ModelAdmin):
    list_display = ("project", "from_status", "to_status", "changed_by", "is_forced", "created_at")
    list_filter = ("is_forced", "to_status")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
