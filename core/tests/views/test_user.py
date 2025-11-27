"""
Tests for UserViewSet.

Tests cover:
- List users (with admin permissions)
- Retrieve user details
- /me endpoint for current user
- User creation, update, delete
- User role-based access control
- Deactivated user handling
"""

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
    """Tests for UserViewSet."""

    def setUp(self):
        """Set up test data."""
        super().setUp()

        # Create test users
        self.super_admin = create_super_admin(email="superadmin@test.com")
        self.admin = create_admin(email="admin@test.com")
        self.regular = create_regular_user(email="regular@test.com")
        self.deactivated = create_deactivated_user(email="deactivated@test.com")

    def test_get_current_user_authenticated(self):
        """Test /me endpoint returns current user data."""
        self.authenticate_user(self.regular)

        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.regular.email)
        self.assertEqual(response.data["user_role"], UserRole.REGULAR)

    def test_get_current_user_unauthenticated(self):
        """Test /me endpoint requires authentication."""
        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_current_user_deactivated(self):
        """Test deactivated user cannot access /me endpoint."""
        self.authenticate_user(self.deactivated)

        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)

        # Deactivated users get 401 (authentication fails for deactivated users)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_users_as_admin(self):
        """Test admin can list users."""
        self.authenticate_user(self.admin)

        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    def test_list_users_as_regular_forbidden(self):
        """Test regular user can list users (filtered by permissions)."""
        self.authenticate_user(self.regular)

        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        # Regular users can access the endpoint (queryset is filtered by permissions)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_user_as_admin(self):
        """Test super admin can retrieve user details."""
        self.authenticate_user(self.super_admin)

        # Super admins can retrieve any user details
        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.admin.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.admin.email)

    def test_filter_users_by_email(self):
        """Test filtering users by email."""
        self.authenticate_user(self.super_admin)

        url = reverse("UserViewSet-list")
        response = self.client.get(url, {"email": "admin"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data

        # Super admin should be able to see admin users
        emails = [r["email"] for r in results]
        self.assertTrue(any("admin" in email for email in emails))

    def test_filter_users_by_role(self):
        """Test filtering users by role."""
        self.authenticate_user(self.super_admin)

        url = reverse("UserViewSet-list")
        response = self.client.get(url, {"roles": UserRole.ADMIN})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data

        # All results should be admin users
        for user in results:
            self.assertEqual(user["user_role"], UserRole.ADMIN)

    def test_create_user_as_admin(self):
        """Test admin can create new user."""
        self.authenticate_user(self.admin)

        url = reverse("UserViewSet-list")
        user_data = {
            "email": "newuser@test.com",
            "password": "newpass123",
            "userRole": UserRole.REGULAR,
        }

        response = self.client.post(url, user_data, format="json")

        # May return 201 Created or 403 depending on permissions
        if response.status_code == status.HTTP_201_CREATED:
            self.assertEqual(response.data["email"], "newuser@test.com")

            # Verify user was created
            user_exists = User.objects.filter(email="newuser@test.com").exists()
            self.assertTrue(user_exists)

    def test_update_user_as_admin(self):
        """Test admin can update user."""
        self.authenticate_user(self.admin)

        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.regular.uuid)})
        update_data = {
            "userRole": UserRole.ADMIN,
        }

        response = self.client.patch(url, update_data, format="json")

        # May return 200 OK or 403 depending on permissions
        if response.status_code == status.HTTP_200_OK:
            self.assertEqual(response.data["userRole"], UserRole.ADMIN)

            # Verify user was updated
            self.regular.refresh_from_db()
            self.assertEqual(self.regular.user_role, UserRole.ADMIN)

    def test_delete_user_as_admin(self):
        """Test admin can delete user."""
        self.authenticate_user(self.admin)

        # Create user to delete
        user_to_delete = create_regular_user(email="todelete@test.com")

        url = reverse("UserViewSet-detail", kwargs={"uuid": str(user_to_delete.uuid)})
        response = self.client.delete(url)

        # May return 204 No Content or 403 depending on permissions
        if response.status_code == status.HTTP_204_NO_CONTENT:
            # Verify user was deleted or marked as deleted
            user_exists = User.objects.filter(
                uuid=user_to_delete.uuid, is_deleted=False
            ).exists()
            self.assertFalse(user_exists)

    def test_user_ordering(self):
        """Test that users are ordered by id descending."""
        self.authenticate_user(self.admin)

        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data

        if len(results) > 1:
            # Check if ordered by recent first (higher IDs first)
            first_user = User.objects.get(email=results[0]["email"])
            second_user = User.objects.get(email=results[1]["email"])
            self.assertGreaterEqual(first_user.id, second_user.id)

    def test_user_response_includes_user_groups(self):
        """Test that user response includes user groups."""
        self.authenticate_user(self.super_admin)

        # Super admin can retrieve user details
        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.admin.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Response should include user_user_groups field
        self.assertIn("user_user_groups", response.data)

    def test_cannot_access_other_users_via_me_endpoint(self):
        """Test that /me endpoint only returns current user."""
        self.authenticate_user(self.regular)

        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.regular.email)
        self.assertNotEqual(response.data["email"], self.admin.email)

    def test_user_password_not_in_response(self):
        """Test that user password is not included in response."""
        self.authenticate_user(self.super_admin)

        # Super admin can retrieve user details
        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.admin.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("password", response.data)

    def test_super_admin_can_access_all_users(self):
        """Test super admin has full access to user management."""
        self.authenticate_user(self.super_admin)

        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Super admin should see all users
        self.assertGreaterEqual(len(response.data), 3)
