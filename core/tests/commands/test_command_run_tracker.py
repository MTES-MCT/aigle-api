"""Tests for CommandRunTrackerMixin — the base that records every core command run.

The mixin distinguishes three entry points, so the tests drive each one directly:
- CLI: ``call_command`` is given a command *instance* with ``_aigle_cli_invocation`` set,
  which mirrors what ``run_from_argv`` does (without its ``connections.close_all()``, which
  would break the test transaction).
- API: ``command_run_uuid_var`` is set, mirroring what the Celery task does.
- bare ``call_command`` (nested commands / tests): neither marker present -> untracked.

``test_cmd`` is the no-op command used as the subject; ``--sleep-seconds 0`` keeps it instant.
"""

import logging
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.base import command_run_uuid_var
from core.management.commands.test_cmd import Command as TestCmdCommand
from core.models.command_run import CommandRun, CommandRunOrigin, CommandRunStatus
from core.services.command_async import CommandAsyncService
from core.tests.base import BaseTestCase


class CommandRunTrackerCliTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        # Real environments run the "aigle" logger at INFO/DEBUG (test settings pin it to
        # WARNING); raise it so the CLI output capture sees the command's log_event() calls.
        self._aigle_logger = logging.getLogger("aigle")
        self._previous_level = self._aigle_logger.level
        self._aigle_logger.setLevel(logging.INFO)

    def tearDown(self):
        self._aigle_logger.setLevel(self._previous_level)
        super().tearDown()

    def _run_cli(self, **options):
        command = TestCmdCommand()
        command._aigle_cli_invocation = True
        call_command(command, sleep_seconds=0, **options)

    def test_cli_run_creates_tracked_row_on_success(self):
        self._run_cli()

        run = CommandRun.objects.get()
        self.assertEqual(run.command_name, "test_cmd")
        self.assertEqual(run.run_origin, CommandRunOrigin.CLI)
        self.assertEqual(run.status, CommandRunStatus.SUCCESS)
        self.assertIsNotNone(run.run_started_at)
        self.assertIsNotNone(run.run_ended_at)
        self.assertLessEqual(run.run_started_at, run.run_ended_at)
        # the aigle-logger output (log_command_event) is captured for CLI runs
        self.assertIn("started", run.output)
        self.assertIn("done", run.output)

    def test_cli_run_captures_arguments_in_kwargs_shape(self):
        # CLI args are stored in the same {"kwargs": {flag: value}} shape the API uses, so the
        # admin UI (ArgumentsDisplay / retry) renders them without crashing on a missing kwargs.
        self._run_cli(note="hello")

        run = CommandRun.objects.get()
        self.assertEqual(run.arguments["kwargs"]["--note"], "hello")
        # an unset store_true flag (default) is omitted
        self.assertNotIn("--fail", run.arguments["kwargs"])

    def test_cli_run_records_error_and_reraises(self):
        with self.assertRaises(CommandError):
            self._run_cli(fail=True)

        run = CommandRun.objects.get()
        self.assertEqual(run.run_origin, CommandRunOrigin.CLI)
        self.assertEqual(run.status, CommandRunStatus.ERROR)
        self.assertIn("on purpose", run.error)
        self.assertIsNotNone(run.run_started_at)
        self.assertIsNotNone(run.run_ended_at)


class CommandRunTrackerApiTests(BaseTestCase):
    def test_api_run_updates_existing_row_via_contextvar(self):
        run = CommandRun.objects.create(
            command_name="test_cmd",
            task_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            run_origin=CommandRunOrigin.API,
            status=CommandRunStatus.PENDING,
        )

        token = command_run_uuid_var.set(str(run.uuid))
        try:
            call_command("test_cmd", sleep_seconds=0)
        finally:
            command_run_uuid_var.reset(token)

        run.refresh_from_db()
        self.assertEqual(run.run_origin, CommandRunOrigin.API)
        self.assertEqual(run.status, CommandRunStatus.SUCCESS)
        self.assertIsNotNone(run.run_started_at)
        self.assertIsNotNone(run.run_ended_at)
        # no second row was opened, and the marker is consumed so nested calls stay untracked
        self.assertEqual(CommandRun.objects.count(), 1)
        self.assertIsNone(command_run_uuid_var.get())

    def test_bare_call_command_is_not_tracked(self):
        call_command("test_cmd", sleep_seconds=0)
        self.assertFalse(CommandRun.objects.exists())


class CancelRunTimingTests(BaseTestCase):
    @patch("celery.result.AsyncResult")
    def test_cancel_stamps_run_ended_at(self, _mock_async_result):
        run = CommandRun.objects.create(
            command_name="test_cmd",
            task_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            run_origin=CommandRunOrigin.API,
            status=CommandRunStatus.RUNNING,
        )

        CommandAsyncService.cancel_task(run.task_id)

        run.refresh_from_db()
        self.assertEqual(run.status, CommandRunStatus.CANCELED)
        self.assertIsNotNone(run.run_ended_at)
        self.assertEqual(run.error, "Task cancelled by user")

    @patch("celery.result.AsyncResult")
    def test_cancel_does_not_touch_already_finished_run(self, _mock_async_result):
        # compare-and-set: a run that already succeeded must survive a late cancel intact.
        run = CommandRun.objects.create(
            command_name="test_cmd",
            task_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            run_origin=CommandRunOrigin.API,
            status=CommandRunStatus.SUCCESS,
            output="real output",
        )

        CommandAsyncService.cancel_task(run.task_id)

        run.refresh_from_db()
        self.assertEqual(run.status, CommandRunStatus.SUCCESS)
        self.assertEqual(run.output, "real output")
        self.assertIsNone(run.error)


class CommandRunFinishRaceTests(BaseTestCase):
    def test_finish_does_not_overwrite_a_canceled_run(self):
        # Simulates the cancel-vs-finish race: the row is CANCELED in the DB while the mixin
        # still holds a stale RUNNING handle. The compare-and-set must leave CANCELED intact.
        run = CommandRun.objects.create(
            command_name="test_cmd",
            task_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            run_origin=CommandRunOrigin.API,
            status=CommandRunStatus.RUNNING,
        )
        stale_handle = CommandRun.objects.get(pk=run.pk)  # mixin's in-memory copy

        CommandRun.objects.filter(pk=run.pk).update(status=CommandRunStatus.CANCELED)

        TestCmdCommand()._aigle_finish_tracking(stale_handle, CommandRunStatus.SUCCESS)

        run.refresh_from_db()
        self.assertEqual(run.status, CommandRunStatus.CANCELED)
