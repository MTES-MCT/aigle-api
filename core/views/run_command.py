# aigle/views.py

from typing import Dict, Any, List, TypedDict
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
from core.utils.tasks import AsyncCommandService
from django.core.management import get_commands, load_command_class
from django.core.management.base import BaseCommand

DEFAULT_OPTIONS = {
    "--version",
    "--verbosity",
    "--settings",
    "--pythonpath",
    "--traceback",
    "--no-color",
    "--force-color",
    "--skip-checks",
    "--help",
}


class CommandParameters(TypedDict):
    name: str
    type: str
    default: str


class CommandWithParameters(TypedDict):
    name: str
    parameters: List[CommandParameters]


def list_commands_with_parameters() -> List[CommandWithParameters]:
    commands = []

    for command_name, app_name in sorted(get_commands().items()):
        if app_name != "core":
            continue

        try:
            command = CommandWithParameters(name=command_name, parameters=[])
            command_obj = load_command_class(app_name, command_name)
            if isinstance(command_obj, BaseCommand):
                parser = command_obj.create_parser("manage.py", command_name)

                for action in parser._actions:
                    if any(opt in DEFAULT_OPTIONS for opt in action.option_strings):
                        continue

                    opts = (
                        ", ".join(action.option_strings)
                        if action.option_strings
                        else action.dest
                    )
                    command_parameters = CommandParameters(
                        name=opts,
                        type=action.type.__name__ if action.type else "str",
                        default=action.default,
                    )
                    command["parameters"].append(command_parameters)

            commands.append(command)
        except Exception as e:
            print(f"Error loading {command_name}: {e}")

    return commands


COMMANDS_AND_PARAMETERS = list_commands_with_parameters()


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
        args: List[Any] = validated_data.get("args", [])
        kwargs: Dict[str, Any] = validated_data.get("kwargs", {})

        task_id: str = AsyncCommandService.run_command_async(
            command_name, *args, **kwargs
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
