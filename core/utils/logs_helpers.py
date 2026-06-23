import contextvars
import logging
import time
from datetime import timedelta
from typing import Optional

from core.utils.command_progress import set_command_progress

# pk of the CommandRun row the current command writes to (set by CommandRunTrackerMixin
# for both CLI and API runs). None when the command is untracked (bare call_command).
current_command_run_pk_var = contextvars.ContextVar(
    "current_command_run_pk", default=None
)


def get_app_logger():
    return logging.getLogger("aigle")


def log_api_call(
    endpoint: str,
    method: str,
    user: str,
    ip: str,
    request_id: str,
    status_code: str,
    duration_ms: Optional[str] = None,
    **kwargs,
):
    logger = get_app_logger()
    logger.info(
        f"API call: {method} {endpoint}",
        extra={
            "endpoint": endpoint,
            "method": method,
            "user": user,
            "ip": ip,
            "request_id": request_id,
            "status_code": status_code,
            "duration_ms": duration_ms,
            **kwargs,
        },
    )


def log_command_event(command_name: str, info: str, **kwargs):
    logger = get_app_logger()
    logger.info(
        f"Command {command_name}: {info}",
        extra={
            "command_name": command_name,
            "category": "command",
            "info": info,
            **kwargs,
        },
    )


def log_command_progress(
    command_name: str, done: int, total: int, start_time: float
) -> None:
    """Uniform progress logging for batch commands.

    Logs ``done/total``, percentage, elapsed time and a linear-rate ETA, then mirrors
    the counters onto the active ``CommandRun`` row so the admin UI can draw a progress bar.

    ``start_time`` is a ``time.monotonic()`` reference captured at command start — monotonic
    (not ``datetime``) so elapsed/ETA stay correct regardless of the user's timezone.
    """
    total = total or 0
    elapsed = time.monotonic() - start_time
    percentage = (done / total * 100) if total else 0
    # Linear extrapolation: remaining = elapsed * (work_left / work_done).
    remaining = elapsed * (total - done) / done if 0 < done < total else 0

    log_command_event(
        command_name=command_name,
        info=(
            f"Progress: {done}/{total} ({percentage:.1f}%) - "
            f"elapsed: {_format_duration(elapsed)} - "
            f"remaining: {_format_duration(remaining)}"
        ),
    )

    pk = current_command_run_pk_var.get()
    if pk is not None:
        set_command_progress(pk, done, total)


def _format_duration(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))
