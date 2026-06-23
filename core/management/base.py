import contextvars
import io
import logging
import uuid as uuid_lib

from django.utils import timezone

from core.models.command_run import CommandRun, CommandRunOrigin, CommandRunStatus
from core.utils.command_progress import clear_command_progress
from core.utils.logs_helpers import current_command_run_pk_var

logger = logging.getLogger(__name__)

# Set by the Celery task (API path) to the uuid of the PENDING row CommandAsyncService
# already created, so the command updates that row instead of opening a new one. It is
# read-and-cleared by the outermost command so a nested call_command() never re-claims it.
command_run_uuid_var = contextvars.ContextVar("command_run_uuid", default=None)

# argparse/Django-internal option dests excluded when recording a CLI run's arguments.
_STANDARD_OPTION_DESTS = {
    "version",
    "verbosity",
    "settings",
    "pythonpath",
    "traceback",
    "no_color",
    "force_color",
    "skip_checks",
}


class CommandRunTrackerMixin:
    """Records each invocation of a core management command in ``CommandRun``.

    - CLI (``python manage.py x``): opens its own row (``run_origin=CLI``) and captures
      the command's ``aigle``-logger output (the channel ``log_command_event`` writes to).
    - API (Celery task): updates the PENDING row identified via ``command_run_uuid_var``;
      live stdout/stderr is streamed to ``output`` by the task, so this mixin leaves it alone.
    - Bare ``call_command()`` (nested commands, tests): left untracked.

    All bookkeeping is best-effort: a tracking failure is logged and swallowed so it can
    never break the command itself (which may run during deploy/CI).
    """

    def run_from_argv(self, argv):
        self._aigle_cli_invocation = True
        super().run_from_argv(argv)

    def execute(self, *args, **options):
        command_run = self._aigle_start_tracking(args, options)
        try:
            result = super().execute(*args, **options)
        except Exception as error:
            self._aigle_finish_tracking(
                command_run, CommandRunStatus.ERROR, error=str(error)
            )
            raise
        self._aigle_finish_tracking(command_run, CommandRunStatus.SUCCESS)
        return result

    def _aigle_command_name(self) -> str:
        return self.__module__.rsplit(".", 1)[-1]

    def _aigle_collect_arguments(self, command_args, options) -> dict:
        """Record the CLI args the user actually passed, in the same {"kwargs": {flag: value}}
        shape the API run-command form uses — so the admin UI displays and can replay them."""
        try:
            parser = self.create_parser("manage.py", self._aigle_command_name())
            kwargs = {}
            for action in parser._actions:
                if not action.option_strings or action.dest in _STANDARD_OPTION_DESTS:
                    continue
                value = options.get(action.dest)
                if value is None or value == action.default:
                    continue
                kwargs[action.option_strings[-1]] = value

            arguments = {"kwargs": kwargs}
            if command_args:
                arguments["args"] = list(command_args)
            return arguments
        except Exception:
            return {"kwargs": {}}

    def _aigle_start_tracking(self, command_args=(), options=None):
        try:
            api_uuid = command_run_uuid_var.get()
            if api_uuid is not None:
                command_run_uuid_var.set(None)  # claimed; nested calls stay untracked
                command_run = CommandRun.objects.filter(uuid=api_uuid).first()
            elif getattr(self, "_aigle_cli_invocation", False):
                command_run = CommandRun.objects.create(
                    command_name=self._aigle_command_name(),
                    task_id=str(uuid_lib.uuid4()),
                    arguments=self._aigle_collect_arguments(
                        command_args, options or {}
                    ),
                    run_origin=CommandRunOrigin.CLI,
                    status=CommandRunStatus.PENDING,
                )
                self._aigle_attach_log_capture()
            else:
                return None

            if command_run is not None:
                command_run.status = CommandRunStatus.RUNNING
                command_run.run_started_at = timezone.now()
                command_run.save(
                    update_fields=["status", "run_started_at", "updated_at"]
                )
                # Expose the row to log_command_progress for the duration of the run.
                self._aigle_progress_token = current_command_run_pk_var.set(
                    command_run.pk
                )
            return command_run
        except Exception:
            logger.exception(
                "CommandRun start tracking failed for %s", self._aigle_command_name()
            )
            return None

    def _aigle_finish_tracking(self, command_run, status, error=None):
        captured_output = self._aigle_detach_log_capture()
        token = getattr(self, "_aigle_progress_token", None)
        if token is not None:
            current_command_run_pk_var.reset(token)
            self._aigle_progress_token = None
        if command_run is None:
            return
        # Progress lived in Redis only for the run's duration — drop it now it's finished.
        clear_command_progress(command_run.pk)
        try:
            now = timezone.now()
            fields = {"status": status, "run_ended_at": now, "updated_at": now}
            if error is not None:
                fields["error"] = error
            if captured_output is not None:
                fields["output"] = captured_output
            # Atomic compare-and-set: only a still-RUNNING row transitions, so a concurrent
            # cancel / reap that already finished the row always wins — and its output, which
            # the task flusher streams on another connection, is never clobbered.
            CommandRun.objects.filter(
                pk=command_run.pk, status=CommandRunStatus.RUNNING
            ).update(**fields)
        except Exception:
            logger.exception("CommandRun finish tracking failed")

    def _aigle_attach_log_capture(self) -> None:
        self._aigle_log_buffer = io.StringIO()
        handler = logging.StreamHandler(self._aigle_log_buffer)
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")
        )
        logging.getLogger("aigle").addHandler(handler)
        self._aigle_log_handler = handler

    def _aigle_detach_log_capture(self):
        handler = getattr(self, "_aigle_log_handler", None)
        if handler is None:
            return None
        try:
            logging.getLogger("aigle").removeHandler(handler)
            return self._aigle_log_buffer.getvalue()
        except Exception:
            logger.exception("CommandRun log capture detach failed")
            return None
        finally:
            self._aigle_log_handler = None
