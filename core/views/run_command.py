# aigle/views.py

from rest_framework.viewsets import ViewSet
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination
from core.serializers.run_command import (
    RunCommandSerializer,
    TaskStatusSerializer,
    CancelTaskSerializer,
)
from core.serializers.command_run import CommandRunSerializer
from core.utils.permissions import SuperAdminRoleModifyActionPermission
from core.utils.run_command import (
    COMMANDS_AND_PARAMETERS,
    CommandParameters,
    parse_parameters,
)
from core.utils.tasks import AsyncCommandService


class CommandAsyncViewSet(ViewSet):
    permission_classes = [SuperAdminRoleModifyActionPermission]

    def list(self, request):
        return Response(COMMANDS_AND_PARAMETERS)

    @action(detail=False, methods=["post"])
    def run(self, request: Request) -> Response:
        serializer = RunCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        command_name = validated_data["command"]
        parameters: CommandParameters = validated_data.get("args", {})
        parsed_parameters = parse_parameters(
            command_name=command_name, parameters=parameters
        )

        # Convert CLI parameter names to Django format for call_command
        django_parameters = {
            key.lstrip("-").replace("-", "_"): value
            for key, value in parsed_parameters.items()
        }

        task_id: str = AsyncCommandService.run_command_async(
            command_name, **django_parameters
        )
        return Response(
            {"task_id": task_id, "status": "started"}, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"])
    def status(self, request: Request, task_id: str = None) -> Response:
        if not task_id:
            return Response(
                {"error": "Task ID is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        task_status = AsyncCommandService.get_task_status(task_id)
        serializer = TaskStatusSerializer(data=task_status)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request: Request, task_id: str = None) -> Response:
        if not task_id:
            return Response(
                {"error": "Task ID is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = CancelTaskSerializer(data={"task_id": task_id})
        serializer.is_valid(raise_exception=True)

        success = AsyncCommandService.cancel_task(task_id)
        return Response(
            {"cancelled": success, "task_id": task_id}, status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get"], url_path="tasks")
    def list_tasks(self, request: Request) -> Response:
        paginator = LimitOffsetPagination()
        paginator.default_limit = 50

        limit = paginator.get_limit(request)
        offset = paginator.get_offset(request)

        command_runs = AsyncCommandService.get_command_runs(limit=limit, offset=offset)
        serializer = CommandRunSerializer(command_runs, many=True)
        return Response(
            {"count": len(command_runs), "results": serializer.data},
            status=status.HTTP_200_OK,
        )
