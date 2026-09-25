from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from core.services.path_validation_progress import PathValidationProgressService
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    add_user_to_group,
    create_super_admin,
    create_admin,
    create_regular_user,
    create_deactivated_user,
    create_user_group,
)
from core.models import User, UserRole
from core.models.user_group import FeatureFlag


class UserViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="superadmin@test.com")
        self.admin = create_admin(email="admin@test.com")
        self.regular = create_regular_user(email="regular@test.com")
        self.deactivated = create_deactivated_user(email="deactivated@test.com")

    def test_get_current_user_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.regular.email)

    def test_get_current_user_unauthenticated(self):
        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_current_user_deactivated(self):
        self.authenticate_user(self.deactivated)
        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_list_users_as_admin(self):
        self.authenticate_user(self.admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    def test_list_users_as_regular(self):
        self.authenticate_user(self.regular)
        url = reverse("UserViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_user_as_super_admin(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.admin.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.admin.email)

    def test_filter_users_by_email(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url, {"email": "admin"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = [r["email"] for r in response.data]
        self.assertTrue(any("admin" in email for email in emails))

    def test_filter_users_by_role(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url, {"roles": UserRole.ADMIN})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for user_data in response.data:
            self.assertEqual(
                user_data.get("userRole") or user_data.get("user_role"),
                UserRole.ADMIN,
            )

    def test_user_ordering(self):
        self.authenticate_user(self.admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data
        if len(results) > 1:
            first_user = User.objects.get(email=results[0]["email"])
            second_user = User.objects.get(email=results[1]["email"])
            self.assertGreaterEqual(first_user.id, second_user.id)

    def test_user_response_includes_user_groups(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.admin.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        has_groups = (
            "userUserGroups" in response.data or "user_user_groups" in response.data
        )
        self.assertTrue(has_groups)

    def test_cannot_access_other_users_via_me_endpoint(self):
        self.authenticate_user(self.regular)
        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.regular.email)
        self.assertNotEqual(response.data["email"], self.admin.email)

    def test_user_password_not_in_response(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.admin.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("password", response.data)

    def test_super_admin_can_access_all_users(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 3)


class UserFeatureFlagsTests(BaseAPITestCase):
    """/users/me carries the union of the feature flags of every group the user
    belongs to: the frontend shows or hides features from that single list."""

    def setUp(self):
        super().setUp()
        self.user = create_regular_user(email="ff-user@test.com")
        self.url = reverse("UserViewSet-get-me")

    def test_no_group_means_no_feature_flag(self):
        self.authenticate_user(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["feature_flags"], [])

    def test_group_without_flag_means_no_feature_flag(self):
        add_user_to_group(self.user, create_user_group(name="FF Plain"))

        self.authenticate_user(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.data["feature_flags"], [])

    def test_one_group_with_the_flag_is_enough(self):
        plain = create_user_group(name="FF Plain")
        with_flag = create_user_group(name="FF With Stats")
        with_flag.feature_flags = [FeatureFlag.STATS]
        with_flag.save()
        add_user_to_group(self.user, plain)
        add_user_to_group(self.user, with_flag)

        self.authenticate_user(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.data["feature_flags"], ["STATS"])

    def test_flag_shared_by_two_groups_is_returned_once(self):
        for name in ["FF Stats A", "FF Stats B"]:
            group = create_user_group(name=name)
            group.feature_flags = [FeatureFlag.STATS]
            group.save()
            add_user_to_group(self.user, group)

        self.authenticate_user(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.data["feature_flags"], ["STATS"])

    def test_user_list_exposes_feature_flags(self):
        group = create_user_group(name="FF Listed")
        group.feature_flags = [FeatureFlag.STATS]
        group.save()
        add_user_to_group(self.user, group)

        self.authenticate_user(create_super_admin(email="ff-admin@test.com"))
        response = self.client.get(reverse("UserViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listed = next(
            item for item in response.data if item["email"] == self.user.email
        )
        self.assertEqual(listed["feature_flags"], ["STATS"])


class UserPathValidationTests(BaseAPITestCase):
    """/users/me/ stays lean: only the admin list and detail join the progress row."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="pv-admin@test.com")
        self.started = create_regular_user(email="pv-started@test.com")
        self.never_started = create_regular_user(email="pv-never@test.com")
        PathValidationProgressService.apply(
            user=self.started, item_count=11, check=[0, 1], uncheck=[]
        )

    def listed(self, response, user):
        return next(item for item in response.data if item["email"] == user.email)

    def test_list_exposes_path_validation(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(reverse("UserViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(self.listed(response, self.never_started)["path_validation"])
        path_validation = self.listed(response, self.started)["path_validation"]
        self.assertIsInstance(path_validation.pop("updated_at"), str)
        self.assertEqual(
            path_validation,
            {
                "checked_items": [0, 1],
                "checked_count": 2,
                "item_count": 11,
                "completed_at": None,
            },
        )

    def test_list_query_count_does_not_grow_with_progress_rows(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-list")

        with CaptureQueriesContext(connection) as with_one_row:
            self.client.get(url)

        for index in range(3):
            PathValidationProgressService.apply(
                user=create_regular_user(email=f"pv-more-{index}@test.com"),
                item_count=11,
                check=[index],
                uncheck=[],
            )

        with CaptureQueriesContext(connection) as with_four_rows:
            response = self.client.get(url)

        self.assertEqual(
            len([item for item in response.data if item["path_validation"]]), 4
        )
        self.assertEqual(
            len(with_four_rows.captured_queries), len(with_one_row.captured_queries)
        )

    def test_retrieve_exposes_path_validation(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            reverse("UserViewSet-detail", kwargs={"uuid": str(self.started.uuid)})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["path_validation"]["checked_items"], [0, 1])

    def test_me_does_not_read_path_validation(self):
        self.authenticate_user(self.started)

        with CaptureQueriesContext(connection) as context:
            response = self.client.get(reverse("UserViewSet-get-me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("path_validation", response.data)
        self.assertFalse(
            any(
                "core_pathvalidationprogress" in query["sql"]
                for query in context.captured_queries
            )
        )

    def test_admin_list_keeps_its_scope(self):
        admin = create_admin(email="pv-group-admin@test.com")
        group = create_user_group(name="PV Admin Group")
        add_user_to_group(admin, group)
        add_user_to_group(self.started, group)
        in_group_never_started = create_regular_user(email="pv-in-group@test.com")
        add_user_to_group(in_group_never_started, group)
        add_user_to_group(self.never_started, create_user_group(name="PV Other Group"))
        other_admin = create_admin(email="pv-other-admin@test.com")
        add_user_to_group(other_admin, group)
        PathValidationProgressService.apply(
            user=other_admin, item_count=11, check=[0], uncheck=[]
        )

        self.authenticate_user(admin)
        response = self.client.get(reverse("UserViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {
                item["email"]: item["path_validation"] is not None
                for item in response.data
            },
            {self.started.email: True, in_group_never_started.email: False},
        )
        self.assertEqual(
            self.listed(response, self.started)["path_validation"]["checked_items"],
            [0, 1],
        )
