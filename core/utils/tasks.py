import logging
import threading
from contextlib import contextmanager
from io import StringIO
from typing import Any, Dict, Optional, Union

from celery import shared_task
from celery.signals import worker_ready
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection as default_connection

from core.models.command_run import CommandRun, CommandRunStatus

logger = logging.getLogger(__name__)


@worker_ready.connect
def reap_orphaned_runs(**_kwargs) -> None:
    """Marks any PENDING/RUNNING row as ERROR on worker boot — with concurrency=1, those are deploy/crash leftovers."""
    try:
        count = CommandRun.objects.filter(
            status__in=[CommandRunStatus.PENDING, CommandRunStatus.RUNNING]
        ).update(
            status=CommandRunStatus.ERROR,
            error="Worker restarted before task could finish.",
        )
        if count:
            logger.warning("Reaped %d orphaned CommandRun row(s) on worker boot", count)
    except Exception:
        logger.exception("Failed to reap orphaned CommandRun rows on worker boot")


MAX_OUTPUT_BYTES = 1_000_000
OUTPUT_FLUSH_INTERVAL_SECONDS = 5.0


class LiveBuffer(StringIO):
    """StringIO that drops the head and prepends a marker when it grows past ``max_bytes``."""

    def __init__(self, max_bytes: int = MAX_OUTPUT_BYTES) -> None:
        super().__init__()
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._truncated = False

    def write(self, s: str) -> int:  # type: ignore[override]
        with self._lock:
            n = super().write(s)
            if self.tell() > self.max_bytes:
                keep = int(self.max_bytes * 0.9)
                tail = self.getvalue()[-keep:]
                marker = (
                    f"... (output truncated, showing last ~{keep // 1024} KB) ...\n"
                )
                self.seek(0)
                self.truncate(0)
                super().write(marker)
                super().write(tail)
                self._truncated = True
            return n

    def snapshot(self) -> str:
        with self._lock:
            return self.getvalue()


class _OutputFlusher(threading.Thread):
    """Persists buffer to CommandRun.output every `interval`s on a thread-local DB connection so flushes survive command-level transaction rollbacks."""

    def __init__(
        self,
        buffer: LiveBuffer,
        command_run_pk: int,
        interval: float = OUTPUT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        super().__init__(daemon=True)
        self.buffer = buffer
        self.command_run_pk = command_run_pk
        self.interval = interval
        self._stop = threading.Event()
        self._last_flushed_len = -1

    def stop(self) -> None:
        self._stop.set()

    def _flush_once(self) -> None:
        text = self.buffer.snapshot()
        if len(text) == self._last_flushed_len:
            return
        try:
            CommandRun.objects.filter(pk=self.command_run_pk).update(output=text)
            self._last_flushed_len = len(text)
        except Exception:
            logger.exception("Failed to flush command output to DB")

    def run(self) -> None:
        try:
            while not self._stop.wait(self.interval):
                self._flush_once()
            self._flush_once()
        finally:
            try:
                default_connection.close()
            except Exception:
                pass


@contextmanager
def capture_aigle_logs(buffer: StringIO):
    """Attach a handler to the ``aigle`` logger so ``log_command_event`` output is captured."""
    handler = logging.StreamHandler(buffer)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    aigle_logger = logging.getLogger("aigle")
    aigle_logger.addHandler(handler)
    try:
        yield
    finally:
        aigle_logger.removeHandler(handler)


def _save_terminal_state(
    command_run: Optional[CommandRun],
    status: str,
    output: str,
    error: Optional[str] = None,
) -> None:
    """Writes the final status — but skips if the row is already finished (CANCELED) so the user's cancel always wins the race."""
    if not command_run:
        return
    try:
        command_run.refresh_from_db(fields=["status"])
    except CommandRun.DoesNotExist:
        return
    if command_run.is_finished():
        return
    command_run.status = status
    command_run.output = output
    if error is not None:
        command_run.error = error
    command_run.save()


@shared_task(bind=True)
def run_management_command(
    self,
    command_name: str,
    command_run_uuid: Optional[str] = None,
    command_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Union[str, Any]]:
    task_id = self.request.id

    # A heavy command may sit in the queue for a long time; refresh the prefork-inherited connection.
    close_old_connections()

    logger.info(
        "run_management_command: command_name=%s, command_run_uuid=%s, command_kwargs=%s",
        command_name,
        command_run_uuid,
        command_kwargs,
    )

    command_run = CommandRun.objects.filter(uuid=command_run_uuid).first()
    if command_run:
        command_run.status = CommandRunStatus.RUNNING
        command_run.save()

    output = LiveBuffer()
    flusher = (
        _OutputFlusher(output, command_run.pk) if command_run is not None else None
    )
    if flusher is not None:
        flusher.start()

    try:
        with capture_aigle_logs(output):
            call_command(
                command_name,
                stdout=output,
                stderr=output,
                **(command_kwargs or {}),
            )

        _save_terminal_state(command_run, CommandRunStatus.SUCCESS, output.snapshot())
        return {
            "status": "success",
            "output": output.snapshot(),
            "task_id": task_id,
        }
    except CommandError as e:
        _save_terminal_state(
            command_run, CommandRunStatus.ERROR, output.snapshot(), str(e)
        )
        return {"status": "error", "error": str(e), "task_id": task_id}
    except Exception as e:
        # No retry: import/heavy commands are rarely safe to re-run blind.
        logger.exception("Unexpected error running %s", command_name)
        _save_terminal_state(
            command_run,
            CommandRunStatus.ERROR,
            output.snapshot(),
            f"Unexpected error: {e}",
        )
        return {
            "status": "error",
            "error": f"Unexpected error: {e}",
            "task_id": task_id,
        }
    finally:
        if flusher is not None:
            flusher.stop()
            flusher.join(timeout=10)
