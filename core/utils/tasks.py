from io import StringIO
from celery import shared_task, current_app
from celery.result import AsyncResult
from django.core.management import call_command
from django.core.management.base import CommandError
from typing import Dict, Any, List, Optional, Tuple, Union
from core.models.command_run import CommandRun, CommandRunStatus


@shared_task(bind=True)
def run_management_command(
    self, command_name: str, *args: Any, **kwargs: Any
) -> Dict[str, Union[str, Any]]:
    task_id = self.request.id
    command_run = CommandRun.objects.filter(task_id=task_id).first()

    if command_run:
        command_run.status = CommandRunStatus.RUNNING
        command_run.save()

    try:
        output = StringIO()
        call_command(command_name, *args, stdout=output, stderr=output, **kwargs)

        if command_run:
            command_run.status = CommandRunStatus.SUCCESS
            command_run.output = output.getvalue()
            command_run.save()

        return {
            "status": "success",
            "output": output.getvalue(),
            "task_id": task_id,
        }
    except CommandError as e:
        if command_run:
            command_run.status = CommandRunStatus.ERROR
            command_run.error = str(e)
            command_run.save()

        return {"status": "error", "error": str(e), "task_id": task_id}
    except Exception as e:
        if command_run:
            command_run.status = CommandRunStatus.ERROR
            command_run.error = f"Unexpected error: {str(e)}"
            command_run.save()

        self.retry(countdown=60, max_retries=3)
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}",
            "task_id": task_id,
        }


@shared_task(bind=True)
def run_custom_command(self, command_name: str, **options: Any) -> str:
    task_id = self.request.id
    command_run = CommandRun.objects.filter(task_id=task_id).first()

    if command_run:
        command_run.status = CommandRunStatus.RUNNING
        command_run.save()

    output = StringIO()
    try:
        call_command(command_name, stdout=output, stderr=output, **options)

        if command_run:
            command_run.status = CommandRunStatus.SUCCESS
            command_run.output = output.getvalue()
            command_run.save()

        return output.getvalue()
    except Exception as e:
        error_msg = f"Error: {str(e)}"

        if command_run:
            command_run.status = CommandRunStatus.ERROR
            command_run.error = error_msg
            command_run.save()

        return error_msg


class AsyncCommandService:
    @staticmethod
    def run_command_async(command_name: str, *args: Any, **kwargs: Any) -> str:
        task = run_management_command.delay(command_name, *args, **kwargs)

        # Create CommandRun record
        CommandRun.objects.create(
            command_name=command_name,
            task_id=task.id,
            arguments={"args": args, "kwargs": kwargs},
            status=CommandRunStatus.PENDING,
        )

        return task.id

    @staticmethod
    def run_custom_command_async(command_name: str, **options: Any) -> str:
        task = run_custom_command.delay(command_name, **options)

        # Create CommandRun record
        CommandRun.objects.create(
            command_name=command_name,
            task_id=task.id,
            arguments={"kwargs": options},
            status=CommandRunStatus.PENDING,
        )

        return task.id

    @staticmethod
    def get_task_status(task_id: str) -> Dict[str, Union[str, Any, None]]:
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
        limit: int = None, offset: int = None
    ) -> Tuple[List[CommandRun], int]:
        """Get CommandRun instances, ordered by most recent first"""
        queryset = CommandRun.objects.all().order_by("-created_at")
        if limit:
            queryset = queryset[offset : offset + limit]
        return list(queryset), queryset.count()

    @staticmethod
    def get_all_tasks() -> List[Dict[str, Any]]:
        """
        DEPRECATED: Use get_command_runs() instead for CommandRun-based tasks.
        This method is kept for backward compatibility with Celery inspection.
        """
        inspect = current_app.control.inspect()
        all_tasks = []

        try:
            # Get active tasks
            active_tasks = inspect.active()
            if active_tasks:
                for worker, tasks in active_tasks.items():
                    for task in tasks:
                        # Active tasks have a different structure - they contain the actual task request
                        all_tasks.append(
                            {
                                "task_id": task.get("id")
                                or task.get("uuid", "unknown"),
                                "name": task.get("name") or task.get("type", "unknown"),
                                "args": task.get("args", []),
                                "kwargs": task.get("kwargs", {}),
                                "worker": worker,
                                "status": "RUNNING",
                                "eta": task.get("eta"),
                                "time_start": task.get("time_start"),
                            }
                        )
        except Exception as e:
            # Log the error but continue with other task types
            print(f"Error getting active tasks: {e}")

        try:
            # Get scheduled tasks
            scheduled_tasks = inspect.scheduled()
            if scheduled_tasks:
                for worker, tasks in scheduled_tasks.items():
                    for task in tasks:
                        # Scheduled tasks have task info nested in "request" key
                        request_info = task.get("request", {})
                        all_tasks.append(
                            {
                                "task_id": request_info.get("id")
                                or request_info.get("uuid", "unknown"),
                                "name": request_info.get("task")
                                or request_info.get("name", "unknown"),
                                "args": request_info.get("args", []),
                                "kwargs": request_info.get("kwargs", {}),
                                "worker": worker,
                                "status": "SCHEDULED",
                                "eta": task.get("eta"),
                                "priority": task.get("priority"),
                            }
                        )
        except Exception as e:
            print(f"Error getting scheduled tasks: {e}")

        try:
            # Get reserved tasks (tasks that are queued but not yet executing)
            reserved_tasks = inspect.reserved()
            if reserved_tasks:
                for worker, tasks in reserved_tasks.items():
                    for task in tasks:
                        # Reserved tasks have similar structure to active tasks
                        all_tasks.append(
                            {
                                "task_id": task.get("id")
                                or task.get("uuid", "unknown"),
                                "name": task.get("name") or task.get("type", "unknown"),
                                "args": task.get("args", []),
                                "kwargs": task.get("kwargs", {}),
                                "worker": worker,
                                "status": "RESERVED",
                                "eta": task.get("eta"),
                            }
                        )
        except Exception as e:
            print(f"Error getting reserved tasks: {e}")

        return all_tasks
