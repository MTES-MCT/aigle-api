from io import StringIO
from celery import shared_task, current_app
from celery.result import AsyncResult
from django.core.management import call_command
from django.core.management.base import CommandError
from typing import Dict, Any, List, Optional, Union


@shared_task(bind=True)
def run_management_command(
    self, command_name: str, *args: Any, **kwargs: Any
) -> Dict[str, Union[str, Any]]:
    try:
        output = StringIO()
        call_command(command_name, *args, stdout=output, stderr=output, **kwargs)
        return {
            "status": "success",
            "output": output.getvalue(),
            "task_id": self.request.id,
        }
    except CommandError as e:
        return {"status": "error", "error": str(e), "task_id": self.request.id}
    except Exception as e:
        self.retry(countdown=60, max_retries=3)
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}",
            "task_id": self.request.id,
        }


@shared_task
def run_custom_command(command_name: str, **options: Any) -> str:
    output = StringIO()
    try:
        call_command(command_name, stdout=output, stderr=output, **options)
        return output.getvalue()
    except Exception as e:
        return f"Error: {str(e)}"


class AsyncCommandService:
    @staticmethod
    def run_command_async(command_name: str, *args: Any, **kwargs: Any) -> str:
        task = run_management_command.delay(command_name, *args, **kwargs)
        return task.id

    @staticmethod
    def get_task_status(task_id: str) -> Dict[str, Union[str, Any, None]]:
        result = AsyncResult(task_id)
        return {
            "task_id": task_id,
            "status": result.status,
            "result": result.result if result.ready() else None,
            "traceback": result.traceback if result.failed() else None,
        }

    @staticmethod
    def get_task_result(task_id: str) -> Optional[Any]:
        result = AsyncResult(task_id)
        if result.ready():
            return result.result
        return None

    @staticmethod
    def cancel_task(task_id: str) -> bool:
        result = AsyncResult(task_id)
        result.revoke(terminate=True)
        return True

    @staticmethod
    def get_all_tasks() -> List[Dict[str, Any]]:
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
