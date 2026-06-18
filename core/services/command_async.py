import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone

from core.models.command_run import CommandRun, CommandRunOrigin, CommandRunStatus
from core.utils.command_progress import clear_command_progress
from core.utils.tasks import run_management_command

logger = logging.getLogger(__name__)


class CommandAsyncService:
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
            run_origin=CommandRunOrigin.API,
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
        from celery.result import AsyncResult

        now = timezone.now()
        # Atomic compare-and-set: only a not-yet-finished row flips to CANCELED, so this
        # never overwrites a run that already succeeded/errored, never races the tracker
        # mixin's terminal write, and never clobbers the live-streamed output field.
        CommandRun.objects.filter(task_id=task_id).exclude(
            status__in=[
                CommandRunStatus.SUCCESS,
                CommandRunStatus.ERROR,
                CommandRunStatus.CANCELED,
            ]
        ).update(
            status=CommandRunStatus.CANCELED,
            error="Task cancelled by user",
            run_ended_at=now,
            updated_at=now,
        )

        AsyncResult(task_id).revoke(terminate=True)

        # Best-effort tidy: revoke is async, so the worker may run one more batch and
        # re-write the key after this clear. That's fine — the serializer never renders
        # progress for a terminal run, and the TTL reaps any leftover key regardless.
        run = CommandRun.objects.filter(task_id=task_id).only("id").first()
        if run is not None:
            clear_command_progress(run.pk)

        return True

    @staticmethod
    def get_command_runs(
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        q: Optional[str] = None,
    ) -> Tuple[List[CommandRun], int]:
        queryset = CommandRun.objects.all().order_by("-created_at")

        if statuses:
            queryset = queryset.filter(status__in=statuses)

        if q:
            queryset = queryset.filter(command_name__icontains=q)

        count = queryset.count()
        if limit:
            start = offset or 0
            queryset = queryset[start : start + limit]
        return list(queryset), count
