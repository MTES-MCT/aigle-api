import uuid
from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status

from core.models import PathValidationProgress, UserActionLog, UserRole
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_deactivated_user,
    create_regular_user,
    create_super_admin,
    create_user,
    create_user_group,
)

ITEM_COUNT = 11
ALL_ITEMS = list(range(ITEM_COUNT))
EMPTY_STATE = {
    "checked_items": [],
    "checked_count": 0,
    "item_count": None,
    "completed_at": None,
    "updated_at": None,
}


class PathValidationProgressTestsBase(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("PathValidationProgressView")
        self.user = create_regular_user(email="pv-user@test.com")

    def patch_progress(self, body, **extra):
        return self.client.patch(self.url, body, format="json", **extra)

    def get_row(self, user=None):
        return PathValidationProgress.objects.get(user=user or self.user)

    def backdate(self, *fields):
        # now() is frozen within the test transaction: backdate to tell a kept date from a new one.
        backdated = timezone.now() - timedelta(days=1)
        PathValidationProgress.objects.filter(user=self.user).update(
            **{field: backdated for field in fields}
        )
        return backdated


class PathValidationProgressAccessTests(PathValidationProgressTestsBase):
    def test_anonymous_is_unauthorized(self):
        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED
        )
        self.assertEqual(
            self.patch_progress({"itemCount": ITEM_COUNT, "check": [0]}).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_inactive_user_is_unauthorized(self):
        self.authenticate_user(create_deactivated_user(email="pv-inactive@test.com"))

        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED
        )
        self.assertEqual(
            self.patch_progress({"itemCount": ITEM_COUNT, "check": [0]}).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_deactivated_role_is_forbidden(self):
        self.authenticate_user(
            create_user(email="pv-deactivated@test.com", user_role=UserRole.DEACTIVATED)
        )

        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            self.patch_progress({"itemCount": ITEM_COUNT, "check": [0]}).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_other_methods_are_not_allowed(self):
        self.authenticate_user(self.user)
        body = {"itemCount": ITEM_COUNT, "check": [0]}

        for method in ["post", "put", "delete"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url, body, format="json")
                self.assertEqual(
                    response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED
                )


class PathValidationProgressViewTests(PathValidationProgressTestsBase):
    def setUp(self):
        super().setUp()
        self.authenticate_user(self.user)

    def test_get_without_row_returns_an_empty_state_and_writes_nothing(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, EMPTY_STATE)
        self.assertEqual(PathValidationProgress.objects.count(), 0)

    def test_regular_user_can_write_their_progress(self):
        response = self.patch_progress({"itemCount": ITEM_COUNT, "check": [0, 3]})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["checked_items"], [0, 3])
        self.assertEqual(response.data["checked_count"], 2)
        self.assertEqual(response.data["item_count"], ITEM_COUNT)
        self.assertIsNone(response.data["completed_at"])

        row = self.get_row()
        self.assertEqual(row.checked_items, 9)
        self.assertEqual(row.item_count, ITEM_COUNT)
        self.assertIsNotNone(row.updated_at)

    def test_writes_from_two_tabs_merge(self):
        self.patch_progress({"itemCount": ITEM_COUNT, "check": [0]})
        response = self.patch_progress({"itemCount": ITEM_COUNT, "check": [1]})
        self.assertEqual(response.data["checked_items"], [0, 1])

        response = self.patch_progress({"itemCount": ITEM_COUNT, "uncheck": [0]})
        self.assertEqual(response.data["checked_items"], [1])

        response = self.patch_progress({"itemCount": ITEM_COUNT, "uncheck": [5]})
        self.assertEqual(response.data["checked_items"], [1])

    def test_first_write_with_only_uncheck_creates_an_empty_row(self):
        response = self.patch_progress({"itemCount": ITEM_COUNT, "uncheck": [2]})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["checked_items"], [])
        self.assertEqual(self.get_row().checked_items, 0)

    def test_same_patch_twice_gives_the_same_state(self):
        body = {"itemCount": ITEM_COUNT, "check": ALL_ITEMS}
        first = self.patch_progress(body).data
        second = self.patch_progress(body).data

        self.assertIsNotNone(second["completed_at"])
        self.assertEqual(first, second)

    def test_completion_date(self):
        response = self.patch_progress(
            {"itemCount": ITEM_COUNT, "check": ALL_ITEMS[:-1]}
        )
        self.assertIsNone(response.data["completed_at"])

        response = self.patch_progress(
            {"itemCount": ITEM_COUNT, "check": [ITEM_COUNT - 1]}
        )
        self.assertIsNotNone(response.data["completed_at"])

        backdated = self.backdate("completed_at")
        response = self.patch_progress({"itemCount": ITEM_COUNT, "check": [0]})
        self.assertEqual(parse_datetime(response.data["completed_at"]), backdated)

        response = self.patch_progress({"itemCount": ITEM_COUNT, "uncheck": [4]})
        self.assertIsNone(response.data["completed_at"])

        response = self.patch_progress({"itemCount": ITEM_COUNT, "check": [4]})
        self.assertGreater(parse_datetime(response.data["completed_at"]), backdated)

    def test_reset_clears_every_item_and_keeps_the_row(self):
        self.patch_progress({"itemCount": ITEM_COUNT, "check": ALL_ITEMS})

        response = self.patch_progress({"itemCount": ITEM_COUNT, "uncheck": ALL_ITEMS})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["checked_items"], [])
        self.assertIsNone(response.data["completed_at"])
        self.assertEqual(self.get_row().checked_items, 0)

    def test_a_longer_list_then_a_stale_build(self):
        self.patch_progress({"itemCount": ITEM_COUNT, "check": ALL_ITEMS})
        backdated = self.backdate("completed_at")

        self.patch_progress({"itemCount": ITEM_COUNT + 1, "check": [ITEM_COUNT]})
        row = self.get_row()
        self.assertEqual(row.item_count, ITEM_COUNT + 1)
        self.assertEqual(row.checked_items, (1 << (ITEM_COUNT + 1)) - 1)
        self.assertGreater(row.completed_at, backdated)

        response = self.patch_progress({"itemCount": ITEM_COUNT, "uncheck": [0]})
        row = self.get_row()
        self.assertEqual(row.item_count, ITEM_COUNT + 1)
        self.assertTrue(row.checked_items & (1 << ITEM_COUNT))
        self.assertIsNone(row.completed_at)
        self.assertIn(ITEM_COUNT, response.data["checked_items"])

    def test_a_longer_list_makes_a_complete_row_incomplete(self):
        self.patch_progress({"itemCount": ITEM_COUNT, "check": ALL_ITEMS})

        response = self.patch_progress(
            {"itemCount": ITEM_COUNT + 1, "uncheck": [ITEM_COUNT]}
        )

        self.assertEqual(response.data["item_count"], ITEM_COUNT + 1)
        self.assertEqual(response.data["checked_items"], ALL_ITEMS)
        self.assertIsNone(response.data["completed_at"])

    def test_invalid_bodies_are_rejected_without_writing(self):
        self.patch_progress({"itemCount": ITEM_COUNT, "check": [0]})
        self.backdate("updated_at")
        row_before = PathValidationProgress.objects.filter(user=self.user).values()[0]

        invalid_bodies = [
            {"itemCount": ITEM_COUNT, "check": [ITEM_COUNT]},
            {"itemCount": ITEM_COUNT, "check": [-1]},
            {"itemCount": ITEM_COUNT, "check": [31]},
            {"itemCount": ITEM_COUNT, "check": ["a"]},
            {"itemCount": ITEM_COUNT, "check": [True]},
            {"itemCount": ITEM_COUNT, "check": 3},
            {"itemCount": 0, "check": [0]},
            {"itemCount": 32, "check": [0]},
            {"check": [0]},
            {"itemCount": ITEM_COUNT},
            {"itemCount": ITEM_COUNT, "check": [], "uncheck": []},
            {"itemCount": ITEM_COUNT, "check": [1], "uncheck": [1]},
            {"itemCount": ITEM_COUNT, "check": [0] * 32},
        ]
        for body in invalid_bodies:
            with self.subTest(body=body):
                response = self.patch_progress(body)

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(
                    PathValidationProgress.objects.filter(user=self.user).values()[0],
                    row_before,
                )

    def test_a_user_only_writes_their_own_row(self):
        other = create_regular_user(email="pv-other@test.com")

        response = self.patch_progress(
            {
                "itemCount": ITEM_COUNT,
                "check": [0],
                "user": other.id,
                "userUuid": str(other.uuid),
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.get_row().checked_items, 1)
        self.assertFalse(PathValidationProgress.objects.filter(user=other).exists())

        self.authenticate_user(other)
        response = self.client.get(self.url)
        self.assertEqual(response.data, EMPTY_STATE)

    def test_patch_runs_one_upsert_and_no_prior_select(self):
        for body in [
            {"itemCount": ITEM_COUNT, "check": [0]},
            {"itemCount": ITEM_COUNT, "check": [1]},
        ]:
            with self.subTest(body=body), CaptureQueriesContext(connection) as context:
                response = self.patch_progress(body)

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                progress_queries = [
                    query["sql"]
                    for query in context.captured_queries
                    if "core_pathvalidationprogress" in query["sql"]
                ]
                self.assertEqual(len(progress_queries), 1)
                self.assertTrue(
                    progress_queries[0]
                    .lstrip()
                    .startswith("INSERT INTO core_pathvalidationprogress")
                )
                self.assertIn("ON CONFLICT", progress_queries[0])

    def test_database_rejects_out_of_range_rows(self):
        for fields in [
            {"checked_items": 2048, "item_count": ITEM_COUNT},
            {"checked_items": 0, "item_count": 0},
        ]:
            with self.subTest(**fields):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    PathValidationProgress.objects.create(user=self.user, **fields)


class PathValidationProgressSuperAdminTests(PathValidationProgressTestsBase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="pv-superadmin@test.com")
        self.authenticate_user(self.super_admin)

    def test_scope_header_is_ignored(self):
        group = create_user_group(name="PV Group")

        response = self.patch_progress(
            {"itemCount": ITEM_COUNT, "check": [0]},
            HTTP_X_USER_GROUP_UUID=str(group.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.get_row(self.super_admin).checked_items, 1)
        self.assertEqual(PathValidationProgress.objects.count(), 1)

        response = self.patch_progress(
            {"itemCount": ITEM_COUNT, "check": [1]},
            HTTP_X_USER_GROUP_UUID=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["checked_items"], [0, 1])

    def test_patch_leaves_no_audit_trail(self):
        user_action_logs_count = UserActionLog.objects.count()
        history_count = self.super_admin.history.count()
        updated_at = self.super_admin.updated_at

        response = self.patch_progress({"itemCount": ITEM_COUNT, "check": [0]})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.super_admin.refresh_from_db()
        self.assertEqual(UserActionLog.objects.count(), user_action_logs_count)
        self.assertEqual(self.super_admin.history.count(), history_count)
        self.assertEqual(self.super_admin.updated_at, updated_at)
