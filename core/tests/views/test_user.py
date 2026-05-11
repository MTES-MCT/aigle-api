from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_admin,
    create_regular_user,
    create_deactivated_user,
)
from core.models import User, UserRole


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
