"""Tests for log_command_progress — the uniform batch-progress helper.

Progress is ephemeral and lives in the Redis-backed cache (LocMemCache under test), keyed by
the active CommandRun via the contextvar. Covers: the formatted log line, the cache write,
the no-active-run no-op, zero-total safety, and that finishing a run clears its progress.
"""

import time

from django.core.cache import cache

from core.management.base import CommandRunTrackerMixin
from core.management.commands.test_cmd import Command as TestCmdCommand
from core.models.command_run import CommandRun, CommandRunOrigin, CommandRunStatus
from core.tests.base import BaseTestCase
from core.utils.command_progress import get_command_progress, set_command_progress
from core.utils.logs_helpers import current_command_run_pk_var, log_command_progress


class LogCommandProgressTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # LocMemCache persists across tests; isolate progress keys

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _make_run(self):
        return CommandRun.objects.create(
            command_name="test_cmd",
            task_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            run_origin=CommandRunOrigin.API,
            status=CommandRunStatus.RUNNING,
        )

    def test_logs_line_and_writes_progress_to_cache(self):
        run = self._make_run()
        token = current_command_run_pk_var.set(run.pk)
        try:
            with self.assertLogs("aigle", level="INFO") as captured:
                # started ~10s ago, halfway done -> ETA also ~10s
                log_command_progress("test_cmd", 5, 10, time.monotonic() - 10)
        finally:
            current_command_run_pk_var.reset(token)

        line = "\n".join(captured.output)
        self.assertIn("5/10 (50.0%)", line)
        self.assertIn("elapsed: 0:00:10", line)
        self.assertIn("remaining: 0:00:10", line)

        self.assertEqual(get_command_progress(run.pk), {"current": 5, "total": 10})

    def test_no_active_run_does_not_write(self):
        # Untracked context (bare call_command / CLI without a row) -> log only, no cache write.
        self.assertIsNone(current_command_run_pk_var.get())
        with self.assertLogs("aigle", level="INFO") as captured:
            log_command_progress("test_cmd", 1, 4, time.monotonic())
        self.assertIn("1/4 (25.0%)", "\n".join(captured.output))

    def test_zero_total_reports_zero_percent(self):
        # File imports / empty inputs can hand total=0; must not ZeroDivisionError.
        with self.assertLogs("aigle", level="INFO") as captured:
            log_command_progress("test_cmd", 0, 0, time.monotonic())
        self.assertIn("0/0 (0.0%)", "\n".join(captured.output))

    def test_finish_tracking_clears_progress(self):
        run = self._make_run()
        set_command_progress(run.pk, 3, 10)
        self.assertIsNotNone(get_command_progress(run.pk))

        # The mixin clears the run's Redis progress on finish so nothing lingers.
        command: CommandRunTrackerMixin = TestCmdCommand()
        command._aigle_finish_tracking(run, CommandRunStatus.SUCCESS)

        self.assertIsNone(get_command_progress(run.pk))
