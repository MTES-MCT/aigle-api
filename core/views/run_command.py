from rest_framework import status
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from core.serializers.command_run import (
    CommandRunSerializer,
    ListTasksParametersSerializer,
)
from core.serializers.run_command import RunCommandSerializer
from core.services.command_async import CommandAsyncService
from core.utils.permissions import SuperAdminRoleModifyActionPermission
from core.utils.run_command import COMMANDS_AND_PARAMETERS, CommandParameters
from core.utils.user_action_log import UserActionLogMixin


class CommandAsyncViewSet(UserActionLogMixin, ViewSet):
    permission_classes = [SuperAdminRoleModifyActionPermission]
    # Speak raw JSON on these routes: the default camelCase renderer/parser would mangle the
    # CLI-flag keys inside CommandRun.arguments (e.g. "--table-name"), which the admin UI
    # replays verbatim into the run-command form. Parameters go in, get stored, and come back
    # out untouched. (Other fields are returned snake_case here too — the frontend models for
    # this admin-only feature expect that.)
    renderer_classes = [JSONRenderer]
    parser_classes = [JSONParser]

    def list(self, request):
        return Response(COMMANDS_AND_PARAMETERS)

    @action(detail=False, methods=["post"])
    def run(self, request: Request) -> Response:
        serializer = RunCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        command_name = validated_data["command"]
        parameters: CommandParameters = validated_data.get("args", {})

        task_id: str = CommandAsyncService.run_command_async(
            command_name=command_name, parameters=parameters
        )
        return Response(
            {"task_id": task_id, "status": "started"}, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request: Request, pk: str = None) -> Response:
        success = CommandAsyncService.cancel_task(pk)
        return Response(
            {"cancelled": success, "task_id": pk}, status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get"], url_path="tasks")
    def list_tasks(self, request: Request) -> Response:
        params_serializer = ListTasksParametersSerializer(data=request.GET)
        params_serializer.is_valid(raise_exception=True)

        paginator = LimitOffsetPagination()
        paginator.default_limit = 50

        limit = paginator.get_limit(request)
        offset = paginator.get_offset(request)

        statuses = params_serializer.validated_data.get("statuses")

        command_runs, count = CommandAsyncService.get_command_runs(
            limit=limit, offset=offset, statuses=statuses
        )
        serializer = CommandRunSerializer(command_runs, many=True)
        return Response(
            {"count": count, "results": serializer.data},
            status=status.HTTP_200_OK,
        )
