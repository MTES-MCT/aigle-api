import json
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


def _serialize_request_data(data):
    if data is None:
        return None
    try:
        json.dumps(data)
        return data
    except (TypeError, ValueError):
        pass
    try:
        return {key: str(value) for key, value in dict(data).items()}
    except Exception:
        return None


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
