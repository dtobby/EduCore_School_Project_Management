from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler


class StaleDataError(Exception):
    """Raised when the client's version doesn't match the database version."""
    pass


class PreconditionError(Exception):
    """Raised when a state machine transition's preconditions are not met."""
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


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

    if isinstance(exc, PreconditionError):
        return Response(
            {
                "code": "precondition_failed",
                "detail": exc.detail,
                "fields": {},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    response = exception_handler(exc, context)

    if response is not None:
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
