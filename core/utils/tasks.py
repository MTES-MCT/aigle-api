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

        # Get active tasks
        active_tasks = inspect.active()
        active_list = []

        if active_tasks:
            for worker, tasks in active_tasks.items():
                for task in tasks:
                    active_list.append(
                        {
                            "task_id": task["id"],
                            "name": task["name"],
                            "args": task["args"],
                            "kwargs": task["kwargs"],
                            "worker": worker,
                            "status": "RUNNING",
                        }
                    )

        # Get scheduled tasks
        scheduled_tasks = inspect.scheduled()
        scheduled_list = []

        if scheduled_tasks:
            for worker, tasks in scheduled_tasks.items():
                for task in tasks:
                    scheduled_list.append(
                        {
                            "task_id": task["request"]["id"],
                            "name": task["request"]["task"],
                            "args": task["request"]["args"],
                            "kwargs": task["request"]["kwargs"],
                            "worker": worker,
                            "status": "SCHEDULED",
                            "eta": task["eta"],
                        }
                    )

        # Get reserved tasks
        reserved_tasks = inspect.reserved()
        reserved_list = []

        if reserved_tasks:
            for worker, tasks in reserved_tasks.items():
                for task in tasks:
                    reserved_list.append(
                        {
                            "task_id": task["id"],
                            "name": task["name"],
                            "args": task["args"],
                            "kwargs": task["kwargs"],
                            "worker": worker,
                            "status": "RESERVED",
                        }
                    )

        return active_list + scheduled_list + reserved_list
