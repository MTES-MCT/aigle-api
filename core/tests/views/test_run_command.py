from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import BadRequest
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status

from core.models.command_run import CommandRun, CommandRunStatus
from core.tests.base import BaseAPITestCase
from core.utils.command_progress import set_command_progress
from core.tests.fixtures.users import (
    create_super_admin,
    create_admin,
    create_regular_user,
)
from core.utils.run_command import COMMANDS_AND_PARAMETERS_MAP, parse_parameters


class CommandAsyncViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="rcadmin@test.com")
        self.admin = create_admin(email="rcmod@test.com")
        self.regular = create_regular_user(email="rcuser@test.com")

    def test_list_as_super_admin(self):
        self.authenticate_user(self.super_admin)
        url = reverse("CommandAsyncViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_as_admin(self):
        self.authenticate_user(self.admin)
        url = reverse("CommandAsyncViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_as_regular(self):
        self.authenticate_user(self.regular)
        url = reverse("CommandAsyncViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_unauthenticated(self):
        url = reverse("CommandAsyncViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class CommandMetadataTests(SimpleTestCase):
    """The metadata served to the run-command form drives which input widget is shown."""

    def setUp(self):
        self.params = COMMANDS_AND_PARAMETERS_MAP["import_custom_zones"]

    def test_store_true_flags_reported_as_bool(self):
        # store_true actions have no argparse `type`; they must still be advertised as
        # bool so the form renders a checkbox instead of a free-text input.
        self.assertEqual(self.params["--force"]["type"], "bool")
        self.assertEqual(self.params["--ignore-categories"]["type"], "bool")

    def test_repeatable_int_param_is_int_and_multiple(self):
        self.assertEqual(self.params["--ids"]["type"], "int")
        self.assertTrue(self.params["--ids"]["multiple"])

    def test_repeatable_str_param_is_str_and_multiple(self):
        self.assertEqual(self.params["--department-codes"]["type"], "str")
        self.assertTrue(self.params["--department-codes"]["multiple"])


class ParseParametersTests(SimpleTestCase):
    COMMAND = "import_custom_zones"

    def test_multiple_ints_from_comma_string(self):
        parsed = parse_parameters(self.COMMAND, {"--ids": "1,2,3"})
        self.assertEqual(parsed["--ids"], [1, 2, 3])

    def test_multiple_ints_from_bare_int_does_not_crash(self):
        # Regression: a NumberInput sent a bare int, and the old code called
        # int.split(",") -> AttributeError -> 500.
        parsed = parse_parameters(self.COMMAND, {"--ids": 5})
        self.assertEqual(parsed["--ids"], [5])

    def test_multiple_ints_from_list(self):
        parsed = parse_parameters(self.COMMAND, {"--ids": [1, 2]})
        self.assertEqual(parsed["--ids"], [1, 2])

    def test_multiple_strips_whitespace_and_drops_empty_fragments(self):
        parsed = parse_parameters(self.COMMAND, {"--ids": "1, 2 , ,3,"})
        self.assertEqual(parsed["--ids"], [1, 2, 3])

    def test_multiple_strings_kept_as_strings(self):
        parsed = parse_parameters(self.COMMAND, {"--department-codes": "34,30"})
        self.assertEqual(parsed["--department-codes"], ["34", "30"])

    def test_invalid_int_raises_bad_request(self):
        with self.assertRaises(BadRequest):
            parse_parameters(self.COMMAND, {"--ids": "abc"})

    def test_single_int_coerced_from_string(self):
        parsed = parse_parameters(self.COMMAND, {"--source-srid": "2154"})
        self.assertEqual(parsed["--source-srid"], 2154)
        self.assertIsInstance(parsed["--source-srid"], int)

    def test_str_param_coerced_from_int(self):
        # Regression: the admin interface can send a numeric value for a str param (a
        # batch id typed as a JSON number). It must reach the command as a string, else
        # raw SQL like `batch_id = %s` fails with "character varying = integer".
        parsed = parse_parameters(
            "import_detections", {"--batch-id": 401, "--tile-set-id": 5}
        )
        self.assertEqual(parsed["--batch-id"], "401")
        self.assertIsInstance(parsed["--batch-id"], str)
        self.assertEqual(parsed["--tile-set-id"], 5)

    def test_bool_values_pass_through(self):
        parsed = parse_parameters(
            self.COMMAND, {"--force": True, "--ignore-categories": False}
        )
        self.assertIs(parsed["--force"], True)
        self.assertIs(parsed["--ignore-categories"], False)

    def test_unknown_command_raises_bad_request(self):
        with self.assertRaises(BadRequest):
            parse_parameters("does_not_exist", {})


class RunCommandEndpointTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="rcrun@test.com")

    @patch("core.views.run_command.CommandAsyncService.run_command_async")
    def test_run_with_multiple_ids_does_not_500(self, mock_run):
        mock_run.return_value = "task-uuid"
        self.authenticate_user(self.super_admin)
        url = reverse("CommandAsyncViewSet-run")

        response = self.client.post(
            url,
            {"command": "import_custom_zones", "args": {"--ids": "1,2,3"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["parameters"]["--ids"], "1,2,3")

    @patch("core.services.command_async.run_management_command.apply_async")
    def test_run_persists_cli_flags_verbatim_and_dispatches_django_dests(
        self, mock_apply
    ):
        # The admin retry replays CommandRun.arguments through the same form, so it's stored
        # exactly as received (raw CLI flags, raw values), while call_command() gets the
        # validated/coerced values under Django dests ("ids").
        self.authenticate_user(self.super_admin)
        url = reverse("CommandAsyncViewSet-run")

        response = self.client.post(
            url,
            {"command": "import_custom_zones", "args": {"--ids": "1,2,3"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        command_run = CommandRun.objects.get(task_id=response.data["task_id"])
        self.assertEqual(command_run.arguments, {"kwargs": {"--ids": "1,2,3"}})

        mock_apply.assert_called_once()
        dispatched_args = mock_apply.call_args.kwargs["args"]
        self.assertEqual(dispatched_args[0], "import_custom_zones")
        self.assertEqual(dispatched_args[2], {"ids": [1, 2, 3]})

    def test_run_with_invalid_parameter_returns_400_and_creates_no_row(self):
        # Validation happens before the row is created, so bad input never leaves a PENDING
        # task behind.
        self.authenticate_user(self.super_admin)

        response = self.client.post(
            reverse("CommandAsyncViewSet-run"),
            {"command": "import_custom_zones", "args": {"--ids": "abc"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(CommandRun.objects.exists())

    def test_tasks_endpoint_filters_by_command_name_q(self):
        CommandRun.objects.create(
            command_name="import_custom_zones",
            task_id="22222222-2222-2222-2222-222222222222",
            status=CommandRunStatus.SUCCESS,
        )
        CommandRun.objects.create(
            command_name="import_parcels",
            task_id="33333333-3333-3333-3333-333333333333",
            status=CommandRunStatus.SUCCESS,
        )
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            reverse("CommandAsyncViewSet-list-tasks"), {"q": "parcel"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["command_name"], "import_parcels")

    def test_tasks_endpoint_exposes_origin_and_timing_fields(self):
        CommandRun.objects.create(
            command_name="test_cmd",
            task_id="44444444-4444-4444-4444-444444444444",
            run_origin="CLI",
            status=CommandRunStatus.RUNNING,
        )
        self.authenticate_user(self.super_admin)

        response = self.client.get(reverse("CommandAsyncViewSet-list-tasks"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()["results"][0]
        # snake_case (this route opts out of the camelCase renderer)
        self.assertEqual(result["run_origin"], "CLI")
        self.assertIn("run_started_at", result)
        self.assertIn("run_ended_at", result)

    def test_tasks_endpoint_exposes_progress_for_running_run(self):
        cache.clear()  # LocMemCache persists across tests
        run = CommandRun.objects.create(
            command_name="create_tile",
            task_id="55555555-5555-5555-5555-555555555555",
            status=CommandRunStatus.RUNNING,
        )
        set_command_progress(run.pk, 3, 10)
        self.authenticate_user(self.super_admin)

        response = self.client.get(reverse("CommandAsyncViewSet-list-tasks"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["results"][0]["progress"], {"current": 3, "total": 10}
        )

    def test_tasks_endpoint_hides_progress_for_finished_run(self):
        # A leftover Redis key (cancel-vs-worker race / TTL window) must never render a
        # progress bar next to a terminal-status run.
        cache.clear()  # LocMemCache persists across tests
        run = CommandRun.objects.create(
            command_name="create_tile",
            task_id="66666666-6666-6666-6666-666666666666",
            status=CommandRunStatus.CANCELED,
        )
        set_command_progress(run.pk, 3, 10)
        self.authenticate_user(self.super_admin)

        response = self.client.get(reverse("CommandAsyncViewSet-list-tasks"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["results"][0]["progress"])

    def test_tasks_endpoint_returns_raw_json_without_camelcase(self):
        # This route opts out of the camelCase renderer so arguments keys round-trip
        # verbatim. The canary: "--table-name" stays as-is and the model field is served
        # snake_case ("command_name", not "commandName").
        CommandRun.objects.create(
            command_name="import_custom_zones",
            task_id="11111111-1111-1111-1111-111111111111",
            arguments={"kwargs": {"--table-name": "inference"}},
            status=CommandRunStatus.PENDING,
        )
        self.authenticate_user(self.super_admin)

        response = self.client.get(reverse("CommandAsyncViewSet-list-tasks"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()["results"][0]
        self.assertEqual(result["arguments"]["kwargs"], {"--table-name": "inference"})
        self.assertIn("command_name", result)
        self.assertNotIn("commandName", result)
