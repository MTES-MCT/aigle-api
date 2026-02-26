from io import StringIO
from celery import shared_task
from django.core.management import call_command
from django.core.management.base import CommandError
from typing import Dict, Any, Optional, Union
from core.models.command_run import CommandRun, CommandRunStatus


@shared_task(bind=True)
def run_management_command(
    self,
    command_name: str,
    command_run_uuid: Optional[str] = None,
    command_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Union[str, Any]]:
    task_id = self.request.id

    # Find CommandRun by UUID if provided, otherwise fallback to task_id
    if command_run_uuid:
        command_run = CommandRun.objects.filter(uuid=command_run_uuid).first()
        if command_run:
            # Update with the actual Celery task_id
            command_run.task_id = task_id
            command_run.status = CommandRunStatus.RUNNING
            command_run.save()
    else:
        command_run = CommandRun.objects.filter(task_id=task_id).first()
        if command_run:
            command_run.status = CommandRunStatus.RUNNING
            command_run.save()

    try:
        output = StringIO()
        call_command(
            command_name, stdout=output, stderr=output, **(command_kwargs or {})
        )

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
def run_custom_command(
    self,
    command_name: str,
    command_run_uuid: Optional[str] = None,
    command_kwargs: Optional[Dict[str, Any]] = None,
) -> str:
    task_id = self.request.id

    # Find CommandRun by UUID if provided, otherwise fallback to task_id
    if command_run_uuid:
        command_run = CommandRun.objects.filter(uuid=command_run_uuid).first()
        if command_run:
            # Update with the actual Celery task_id
            command_run.task_id = task_id
            command_run.status = CommandRunStatus.RUNNING
            command_run.save()
    else:
        command_run = CommandRun.objects.filter(task_id=task_id).first()
        if command_run:
            command_run.status = CommandRunStatus.RUNNING
            command_run.save()

    output = StringIO()
    try:
        call_command(
            command_name, stdout=output, stderr=output, **(command_kwargs or {})
        )

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
