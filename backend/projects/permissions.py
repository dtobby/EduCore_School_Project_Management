from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsTeacher(BasePermission):
    """Allow access only to users with the TEACHER role."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_teacher


class IsStudent(BasePermission):
    """Allow access only to users with the STUDENT role."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_student


class IsAdminRole(BasePermission):
    """Allow access only to users with the ADMIN role."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_admin_role


class IsAdminOrReadOnly(BasePermission):
    """Admin can do anything; other authenticated users get read-only."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_admin_role


class IsProjectOwner(BasePermission):
    """
    Object-level: only the teacher who created the project can modify it.
    Used alongside IsTeacher at the endpoint level.
    """

    def has_object_permission(self, request, view, obj):
        return obj.created_by == request.user


class IsAssignedToProject(BasePermission):
    """
    Object-level: student can only access projects they are assigned to.
    Used alongside IsStudent at the endpoint level.
    """

    def has_object_permission(self, request, view, obj):
        return request.user in obj.assigned_students.all()
