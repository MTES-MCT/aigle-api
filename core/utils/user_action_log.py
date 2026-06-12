import logging

from rest_framework.request import Request
from rest_framework.response import Response

from core.models.user import UserRole
from core.models.user_action_log import UserActionLog, UserActionLogAction

logger = logging.getLogger(__name__)


MODIFY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_ACTION_NAME_TO_ENUM = {
    "create": UserActionLogAction.CREATE,
    "update": UserActionLogAction.UPDATE,
    "partial_update": UserActionLogAction.PARTIAL_UPDATE,
    "destroy": UserActionLogAction.DESTROY,
}


REDACTED_PLACEHOLDER = "[REDACTED]"

# Scalars JSON can represent directly; any other leaf is stored as its str().
_JSON_SCALARS = (str, int, float, bool)


def _is_sensitive_key(key) -> bool:
    """A field is sensitive if it looks like a password, whatever the naming
    convention (password, re_password, currentPassword, newPassword, ...)."""
    return isinstance(key, str) and "password" in key.lower()


def _sanitize(value):
    """Recursively produce a JSON-serializable, password-redacted copy of
    ``value`` for storage in ``UserActionLog.data``.

    Redaction and serialization happen in a single pass so nested secrets are
    caught even when the surrounding structure is not natively
    JSON-serializable (e.g. a multipart ``QueryDict`` carrying an uploaded
    file): containers are always recursed into, and only non-serializable
    *leaves* are replaced by their ``str()`` repr. Sensitive keys are replaced
    by the placeholder at any depth. Never mutates the input."""
    if value is None or isinstance(value, _JSON_SCALARS):
        return value
    if isinstance(value, dict):
        return {
            key: REDACTED_PLACEHOLDER if _is_sensitive_key(key) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return str(value)


def _serialize_request_data(data):
    """Return a JSON-serializable, password-redacted snapshot of the request
    body, suitable for storing in ``UserActionLog.data``."""
    return _sanitize(data)


class UserActionLogMixin:
    """
    ViewSet mixin that logs a UserActionLog entry after every successful
    modify request performed by a SUPER_ADMIN. Must be placed before the
    ViewSet base class in the MRO so its finalize_response runs first.
    """

    def finalize_response(
        self, request: Request, response: Response, *args, **kwargs
    ) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)

        if not self._should_log_user_action(request, response):
            return response

        try:
            action_name = getattr(self, "action", None) or ""
            action_enum = _ACTION_NAME_TO_ENUM.get(
                action_name, UserActionLogAction.CUSTOM
            )

            UserActionLog.objects.create(
                user=request.user,
                route=request.path,
                action=action_enum,
                data=_serialize_request_data(getattr(request, "data", None)),
            )
        except Exception:
            logger.exception("Failed to write UserActionLog")

        return response

    @staticmethod
    def _should_log_user_action(request: Request, response: Response) -> bool:
        if request.method not in MODIFY_METHODS:
            return False
        if not (200 <= response.status_code < 300):
            return False
        user = getattr(request, "user", None)
        if user is None or user.is_anonymous:
            return False
        return getattr(user, "user_role", None) == UserRole.SUPER_ADMIN
