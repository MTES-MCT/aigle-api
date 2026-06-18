"""Ephemeral command-run progress, stored in Redis (the app cache) only while a command runs.

Progress is transient: it is written per batch by ``log_command_progress``, read by the
run-command admin list, cleared by ``CommandRunTrackerMixin`` when the command finishes, and
carries a TTL as a backstop. Losing it is harmless — the logs hold the authoritative trail —
so every access is fail-open (a backend error degrades to "no progress", never raises).
"""

import logging
from typing import Dict, List, Optional, TypedDict

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Backstop only — finished runs are cleared explicitly; this just reaps progress for runs
# whose process died without finishing (deploy/crash) so nothing lingers in Redis forever.
PROGRESS_TTL_SECONDS = 24 * 60 * 60


class CommandProgress(TypedDict):
    current: int
    total: int


def _key(command_run_pk: int) -> str:
    return f"aigle:command_progress:{command_run_pk}"


def set_command_progress(command_run_pk: int, current: int, total: int) -> None:
    try:
        cache.set(
            _key(command_run_pk),
            {"current": current, "total": total},
            timeout=PROGRESS_TTL_SECONDS,
        )
    except Exception:
        logger.exception("Failed to set command progress for run %s", command_run_pk)


def get_command_progress(command_run_pk: int) -> Optional[CommandProgress]:
    try:
        return cache.get(_key(command_run_pk))
    except Exception:
        logger.exception("Failed to get command progress for run %s", command_run_pk)
        return None


def get_command_progress_many(
    command_run_pks: List[int],
) -> Dict[int, CommandProgress]:
    """Bulk fetch so the run-command list serializes N rows without N Redis round-trips."""
    if not command_run_pks:
        return {}
    try:
        key_to_pk = {_key(pk): pk for pk in command_run_pks}
        found = cache.get_many(list(key_to_pk.keys()))
        return {key_to_pk[key]: value for key, value in found.items()}
    except Exception:
        logger.exception("Failed to bulk-get command progress")
        return {}


def clear_command_progress(command_run_pk: int) -> None:
    try:
        cache.delete(_key(command_run_pk))
    except Exception:
        logger.exception("Failed to clear command progress for run %s", command_run_pk)
