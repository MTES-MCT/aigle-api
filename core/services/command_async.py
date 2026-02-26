from typing import Any, Dict, List, Optional, Tuple, Union
from celery.result import AsyncResult
from core.models.command_run import CommandRun, CommandRunStatus
from core.utils.tasks import run_management_command, run_custom_command
import uuid


class CommandAsyncService:
    """Service for handling asynchronous command execution."""

    @staticmethod
    def run_command_async(command_name: str, **kwargs: Any) -> str:
        """Run Django management command asynchronously."""
        # Generate unique temporary task_id to avoid constraint violation
        temp_task_id = f"pending-{str(uuid.uuid4())[:8]}"

        # Create CommandRun record first
        command_run = CommandRun.objects.create(
            command_name=command_name,
            task_id=temp_task_id,
            arguments={"kwargs": kwargs},
            status=CommandRunStatus.PENDING,
        )

        # Pass the UUID and command kwargs as explicit parameters
        # to avoid Celery *args serialization issues
        task = run_management_command.delay(  # type: ignore[operator]
            command_name, str(command_run.uuid), kwargs
        )

        return task.id

    @staticmethod
    def run_custom_command_async(command_name: str, **options: Any) -> str:
        """Run custom Django command asynchronously."""
        # Generate unique temporary task_id to avoid constraint violation
        temp_task_id = f"pending-{str(uuid.uuid4())[:8]}"

        # Create CommandRun record first
        command_run = CommandRun.objects.create(
            command_name=command_name,
            task_id=temp_task_id,
            arguments={"kwargs": options},
            status=CommandRunStatus.PENDING,
        )

        # Pass the UUID and command kwargs as explicit parameters
        # to avoid Celery serialization issues
        task = run_custom_command.delay(command_name, str(command_run.uuid), options)  # type: ignore[operator]

        return task.id

    @staticmethod
    def get_task_status(task_id: str) -> Dict[str, Union[str, Any, None]]:
        """Get status of a task by ID."""
        command_run = CommandRun.objects.filter(task_id=task_id).first()

        if command_run:
            return {
                "task_id": task_id,
                "status": command_run.status,
                "result": {"output": command_run.output, "error": command_run.error}
                if command_run.is_finished()
                else None,
                "traceback": command_run.error
                if command_run.status == CommandRunStatus.ERROR
                else None,
                "command_name": command_run.command_name,
                "arguments": command_run.arguments,
                "created_at": command_run.created_at.isoformat(),
                "updated_at": command_run.updated_at.isoformat(),
            }

        # Fallback to Celery result if CommandRun not found
        result = AsyncResult(task_id)
        return {
            "task_id": task_id,
            "status": result.status,
            "result": result.result if result.ready() else None,
            "traceback": result.traceback if result.failed() else None,
        }

    @staticmethod
    def get_task_result(task_id: str) -> Optional[Any]:
        """Get result of a completed task."""
        command_run = CommandRun.objects.filter(task_id=task_id).first()

        if command_run and command_run.is_finished():
            if command_run.status == CommandRunStatus.SUCCESS:
                return command_run.output
            else:
                return command_run.error

        # Fallback to Celery result if CommandRun not found
        result = AsyncResult(task_id)
        if result.ready():
            return result.result
        return None

    @staticmethod
    def cancel_task(task_id: str) -> bool:
        """Cancel a running task."""
        # Update CommandRun status if exists
        command_run = CommandRun.objects.filter(task_id=task_id).first()
        if command_run and not command_run.is_finished():
            command_run.status = CommandRunStatus.CANCELED
            command_run.error = "Task cancelled by user"
            command_run.save()

        # Cancel the Celery task
        result = AsyncResult(task_id)
        result.revoke(terminate=True)
        return True

    @staticmethod
    def get_command_runs(
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        statuses: Optional[List[str]] = None,
    ) -> Tuple[List[CommandRun], int]:
        """Get CommandRun instances with optional filtering and pagination."""
        queryset = CommandRun.objects.all().order_by("-created_at")

        if statuses:
            queryset = queryset.filter(status__in=statuses)

        count = queryset.count()
        if limit:
            start = offset or 0
            queryset = queryset[start : start + limit]
        return list(queryset), count

    @staticmethod
    def validate_task_id(task_id: str) -> bool:
        """Validate if task ID exists."""
        return CommandRun.objects.filter(task_id=task_id).exists()

    @staticmethod
    def parse_command_parameters(
        command_name: str, parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Parse and convert CLI parameter names to Django format."""
        from core.utils.run_command import parse_parameters

        parsed_parameters = parse_parameters(
            command_name=command_name, parameters=parameters
        )

        # Convert CLI parameter names to Django format for call_command
        return {
            key.lstrip("-").replace("-", "_"): value
            for key, value in parsed_parameters.items()
        }
