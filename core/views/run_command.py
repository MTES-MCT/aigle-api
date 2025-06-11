# aigle/views.py

from typing import Dict, Any, Union
from rest_framework.viewsets import ViewSet
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from core.serializers.run_command import (
    RunCommandSerializer,
    TaskStatusSerializer,
    CancelTaskSerializer,
)
from core.utils.permissions import SuperAdminRoleModifyActionPermission
from core.utils.run_command import COMMANDS_AND_PARAMETERS, validate_parameters
from core.utils.tasks import AsyncCommandService


class CommandAsyncViewSet(ViewSet):
    permission_classes = [SuperAdminRoleModifyActionPermission]

    def list(self, request):
        return Response(COMMANDS_AND_PARAMETERS)

    @action(detail=False, methods=["post"])
    def run(self, request: Request) -> Response:
        serializer = RunCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data: Dict[str, Any] = serializer.validated_data
        command_name: str = validated_data["command"]
        parameters: Dict[str, Union[bool, str, int]] = validated_data.get("args", {})
        validate_parameters(command_name=command_name, parameters=parameters)

        task_id: str = AsyncCommandService.run_command_async(command_name, **parameters)
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

    @action(detail=True, methods=["post"])
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
