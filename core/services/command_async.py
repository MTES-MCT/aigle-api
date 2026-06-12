import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.models.command_run import CommandRun, CommandRunStatus
from core.utils.tasks import run_management_command

logger = logging.getLogger(__name__)


class CommandAsyncService:
    """Service for handling asynchronous command execution."""

    @staticmethod
    def run_command_async(command_name: str, parameters: Dict[str, Any]) -> str:
        """Run a Django management command asynchronously via Celery.

        ``parameters`` is exactly what the client sent — keyed by the raw CLI flags
        ("--table-name"), the same keys the run-command form uses. It is stored verbatim in
        ``CommandRun.arguments`` and served back untouched so the admin UI can replay a run.
        call_command() needs validated/coerced values under argparse dests ("table_name"),
        so that form is derived only for dispatch, never persisted.
        """
        from core.utils.run_command import parse_parameters

        # Validates the input (raises BadRequest -> 400) and coerces values to their declared
        # types — done before creating the row so bad input never leaves a PENDING task.
        parsed = parse_parameters(command_name=command_name, parameters=parameters)
        command_kwargs = {
            key.lstrip("-").replace("-", "_"): value for key, value in parsed.items()
        }

        command_run_uuid = str(uuid.uuid4())
        command_run = CommandRun.objects.create(
            command_name=command_name,
            task_id=command_run_uuid,
            arguments={"kwargs": parameters},
            status=CommandRunStatus.PENDING,
        )

        logger.info(
            "run_command_async: command_name=%s, kwargs=%s, uuid=%s",
            command_name,
            command_kwargs,
            command_run_uuid,
        )

        run_management_command.apply_async(
            args=[command_name, str(command_run.uuid), command_kwargs],
            task_id=command_run_uuid,
        )

        return command_run_uuid

    @staticmethod
    def cancel_task(task_id: str) -> bool:
        """Mark a CommandRun as canceled and revoke the Celery task."""
        from celery.result import AsyncResult

        command_run = CommandRun.objects.filter(task_id=task_id).first()
        if command_run and not command_run.is_finished():
            command_run.status = CommandRunStatus.CANCELED
            command_run.error = "Task cancelled by user"
            command_run.save()

        AsyncResult(task_id).revoke(terminate=True)
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
