from unittest.mock import patch

from django.core.exceptions import BadRequest
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status

from core.services.command_async import CommandAsyncService
from core.tests.base import BaseAPITestCase
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

    def test_bool_values_pass_through(self):
        parsed = parse_parameters(
            self.COMMAND, {"--force": True, "--ignore-categories": False}
        )
        self.assertIs(parsed["--force"], True)
        self.assertIs(parsed["--ignore-categories"], False)

    def test_unknown_command_raises_bad_request(self):
        with self.assertRaises(BadRequest):
            parse_parameters("does_not_exist", {})

    def test_parse_command_parameters_maps_cli_names_to_django_kwargs(self):
        django_kwargs = CommandAsyncService.parse_command_parameters(
            self.COMMAND, {"--ids": "1,2,3", "--force": True}
        )
        self.assertEqual(django_kwargs["ids"], [1, 2, 3])
        self.assertIs(django_kwargs["force"], True)


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
        self.assertEqual(kwargs["ids"], [1, 2, 3])
