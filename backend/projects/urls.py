from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ProjectViewSet, TaskViewSet

router = DefaultRouter()
router.register("projects", ProjectViewSet, basename="project")

_task_list   = TaskViewSet.as_view({"get": "list",   "post": "create"})
_task_detail = TaskViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"})
_task_weights = TaskViewSet.as_view({"put": "bulk_weights"})
_task_toggle  = TaskViewSet.as_view({"post": "toggle_completion"})

urlpatterns = [
    path("", include(router.urls)),
    path("projects/<int:project_pk>/tasks/", _task_list, name="project-task-list"),
    # weights/ before <int:pk>/ so it matches first (though <int:pk> won't match the string "weights")
    path("projects/<int:project_pk>/tasks/weights/", _task_weights, name="project-task-weights"),
    path("projects/<int:project_pk>/tasks/<int:pk>/", _task_detail, name="project-task-detail"),
    path("projects/<int:project_pk>/tasks/<int:pk>/toggle/", _task_toggle, name="project-task-toggle"),
]
