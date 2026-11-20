from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler


class StaleDataError(Exception):
    """Raised when the client's version doesn't match the database version."""
    pass


def custom_exception_handler(exc, context):
    if isinstance(exc, StaleDataError):
        return Response(
            {
                "code": "stale_data",
                "detail": "The data has changed since you last loaded it. Reload and try again.",
                "fields": {},
            },
            status=status.HTTP_409_CONFLICT,
        )

    response = exception_handler(exc, context)

    if response is not None:
        # exc.detail.code holds the per-instance code (e.g. "user_inactive")
        # exc.default_code holds the class-level fallback (e.g. "authentication_failed")
        detail_obj = getattr(exc, "detail", None)
        code = getattr(detail_obj, "code", None) or getattr(exc, "default_code", "error")

        if isinstance(exc, ValidationError) and isinstance(exc.detail, dict):
            detail = "Validation failed."
            fields = exc.detail
        elif isinstance(getattr(exc, "detail", None), list):
            detail = " ".join(str(d) for d in exc.detail)
            fields = {}
        else:
            detail = str(getattr(exc, "detail", str(exc)))
            fields = {}

        response.data = {"code": code, "detail": detail, "fields": fields}

    return response
