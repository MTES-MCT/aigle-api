import json

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status

from core.models.user_action_log import UserActionLog, UserActionLogAction
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_admin,
    create_regular_user,
)
from core.utils.user_action_log import (
    REDACTED_PLACEHOLDER,
    _sanitize,
    _serialize_request_data,
)


class UserActionLogViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="ualadmin@test.com")
        self.admin = create_admin(email="ualmod@test.com")
        self.regular = create_regular_user(email="ualuser@test.com")

    def test_list_as_super_admin(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserActionLogViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_as_admin_forbidden(self):
        self.authenticate_user(self.admin)
        url = reverse("UserActionLogViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse("UserActionLogViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_unauthenticated(self):
        url = reverse("UserActionLogViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_user_redacts_password_in_action_log(self):
        """The cleartext password sent when creating a user must never be
        persisted in the audit log — it is replaced by a placeholder."""
        self.authenticate_user(self.super_admin)
        secret = "SuperSecret123!"

        url = reverse("UserViewSet-list")
        response = self.client.post(
            url,
            {
                "email": "redaction-target@test.com",
                "userRole": "REGULAR",
                "password": secret,
                "userUserGroups": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        log = (
            UserActionLog.objects.filter(
                route="/api/users/", action=UserActionLogAction.CREATE
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.data["password"], REDACTED_PLACEHOLDER)
        # Non-sensitive fields are preserved, and the secret leaks nowhere.
        self.assertEqual(log.data["email"], "redaction-target@test.com")
        self.assertNotIn(secret, json.dumps(log.data))


class SanitizeAuditDataTests(SimpleTestCase):
    """Unit tests for the audit-log sanitizer (redaction + serialization, no DB)."""

    def test_redacts_top_level_password(self):
        result = _sanitize({"email": "a@b.c", "password": "secret"})
        self.assertEqual(result, {"email": "a@b.c", "password": REDACTED_PLACEHOLDER})

    def test_redacts_password_nested_in_list(self):
        result = _sanitize({"users": [{"email": "a@b.c", "password": "secret"}]})
        self.assertEqual(result["users"][0]["password"], REDACTED_PLACEHOLDER)

    def test_redacts_naming_convention_variants(self):
        result = _sanitize(
            {
                "password": "x",
                "rePassword": "x",
                "current_password": "x",
                "newPassword": "x",
            }
        )
        self.assertTrue(all(v == REDACTED_PLACEHOLDER for v in result.values()))

    def test_preserves_non_sensitive_values(self):
        payload = {"email": "a@b.c", "userRole": "REGULAR", "nested": {"score": 0.9}}
        self.assertEqual(_sanitize(payload), payload)

    def test_does_not_mutate_input(self):
        payload = {"password": "secret", "items": [{"password": "secret2"}]}
        _sanitize(payload)
        self.assertEqual(payload["password"], "secret")
        self.assertEqual(payload["items"][0]["password"], "secret2")

    def test_non_serializable_value_does_not_hide_nested_secret(self):
        """A non-JSON-serializable leaf (e.g. an uploaded file) must not cause a
        nested secret to slip through: containers are still recursed, only the
        leaf is stringified. Guards the multipart/QueryDict code path."""

        class Unserializable:
            def __str__(self):
                return "FILE_REPR"

        payload = {
            "password": "leaky",
            "file": Unserializable(),
            "nested": {"newPassword": "leaky2"},
        }
        result = _sanitize(payload)

        dumped = json.dumps(result)  # must be JSON-serializable
        self.assertNotIn("leaky", dumped)
        self.assertEqual(result["password"], REDACTED_PLACEHOLDER)
        self.assertEqual(result["nested"]["newPassword"], REDACTED_PLACEHOLDER)
        self.assertEqual(result["file"], "FILE_REPR")

    def test_serialize_request_data_redacts_and_handles_none(self):
        self.assertIsNone(_serialize_request_data(None))
        self.assertEqual(
            _serialize_request_data({"password": "secret"}),
            {"password": REDACTED_PLACEHOLDER},
        )


class RedactPasswordsMigrationTests(BaseAPITestCase):
    """Covers the 0118 data migration that scrubs already-stored cleartext
    passwords from existing UserActionLog rows."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="migadmin@test.com")

    def test_migration_redacts_existing_rows(self):
        from importlib import import_module

        from django.apps import apps as global_apps

        migration = import_module(
            "core.migrations.0118_redact_user_action_log_passwords"
        )

        secret = "PLAINTEXT_SECRET"
        leaky = UserActionLog.objects.create(
            user=self.super_admin,
            route="/api/users/",
            action=UserActionLogAction.CREATE,
            data={
                "email": "x@y.z",
                "password": secret,
                "user_user_groups": [{"password": "NESTED_SECRET"}],
            },
        )
        clean = UserActionLog.objects.create(
            user=self.super_admin,
            route="/api/user-group/",
            action=UserActionLogAction.CREATE,
            data={"name": "group", "count": 3},
        )
        null_data = UserActionLog.objects.create(
            user=self.super_admin,
            route="/api/x/",
            action=UserActionLogAction.CUSTOM,
            data=None,
        )

        migration.redact_passwords(global_apps, None)

        leaky.refresh_from_db()
        clean.refresh_from_db()
        null_data.refresh_from_db()

        self.assertEqual(leaky.data["password"], REDACTED_PLACEHOLDER)
        self.assertEqual(
            leaky.data["user_user_groups"][0]["password"], REDACTED_PLACEHOLDER
        )
        self.assertEqual(leaky.data["email"], "x@y.z")
        self.assertNotIn(secret, json.dumps(leaky.data))
        # Non-sensitive rows and null-data rows are left untouched.
        self.assertEqual(clean.data, {"name": "group", "count": 3})
        self.assertIsNone(null_data.data)
