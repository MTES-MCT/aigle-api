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
from core.serializers.command_run import (
    CommandRunSerializer,
    ListTasksParametersSerializer,
)
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
    def status(self, request: Request, pk: str = None) -> Response:
        if not pk:
            return Response(
                {"error": "Task ID is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        task_status = AsyncCommandService.get_task_status(pk)
        serializer = TaskStatusSerializer(data=task_status)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request: Request, pk: str = None) -> Response:
        if not pk:
            return Response(
                {"error": "Task ID is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = CancelTaskSerializer(data={"task_id": pk})
        serializer.is_valid(raise_exception=True)

        success = AsyncCommandService.cancel_task(pk)
        return Response(
            {"cancelled": success, "task_id": pk}, status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get"], url_path="tasks")
    def list_tasks(self, request: Request) -> Response:
        # Validate query parameters
        params_serializer = ListTasksParametersSerializer(data=request.GET)
        params_serializer.is_valid(raise_exception=True)

        paginator = LimitOffsetPagination()
        paginator.default_limit = 50

        limit = paginator.get_limit(request)
        offset = paginator.get_offset(request)

        # Get validated statuses from serializer
        statuses = params_serializer.validated_data.get("statuses")

        command_runs, count = AsyncCommandService.get_command_runs(
            limit=limit, offset=offset, statuses=statuses
        )
        serializer = CommandRunSerializer(command_runs, many=True)
        return Response(
            {"count": count, "results": serializer.data},
            status=status.HTTP_200_OK,
        )
