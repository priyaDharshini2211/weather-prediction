import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Expected, user-facing error with an HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def api_exception_handler(exc, context):
    """Consistent error body: {"error": "<message>"} - never leaks stack traces."""
    if isinstance(exc, ApiError):
        return Response({"error": exc.message}, status=exc.status)

    response = exception_handler(exc, context)
    if response is not None:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        response.data = {"error": str(detail or response.data)}
        return response

    logger.exception("Unhandled error", exc_info=exc)
    return Response({"error": "Internal server error"}, status=500)
