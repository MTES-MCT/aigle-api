"""Regression tests for the broken-access-control fixes in core/utils/permissions.py.

Before the fix, the role permission classes let any authenticated user perform write
actions:

* ``CustomRolePermission`` allowed a non-privileged user whenever ``view.action`` was not
  in a hard-coded list of CRUD write actions. Custom ``@action`` write endpoints (e.g.
  run-command ``run``, tile-set ``bulk_create``) were never in that list, so they were
  reachable by any authenticated user.
* ``AdminRolePermission`` was built with an empty ``restricted_actions`` list, so *every*
  action — including ``create``/``update``/``destroy`` on ``UserViewSet`` — was allowed
  for any authenticated user. A REGULAR user could reset a SUPER_ADMIN's password and take
  over the account.

The fix gates write methods on the privileged role and makes DEACTIVATED accounts (whose
JWT may still be valid) be denied everywhere.
"""

from django.urls import reverse
from rest_framework import status

from core.models.user import UserRole
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_regular_user,
    create_super_admin,
)


def _results(response):
    """Return the list of objects from a (possibly paginated) list response."""
    data = response.json()
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


class UserAccountTakeoverTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.regular = create_regular_user(email="sec_regular@test.com")

    def test_regular_cannot_reset_another_users_password(self):
        # The headline vulnerability: account takeover via password reset.
        victim = create_super_admin(
            email="sec_victim@test.com", password="OriginalPwd!1"
        )
        self.authenticate_user(self.regular)

        url = reverse("UserViewSet-detail", kwargs={"uuid": victim.uuid})
        response = self.client.patch(url, {"password": "PwnedPwd!999"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        victim.refresh_from_db()
        self.assertTrue(victim.check_password("OriginalPwd!1"))

    def test_regular_cannot_create_user(self):
        self.authenticate_user(self.regular)
        response = self.client.post(
            reverse("UserViewSet-list"),
            {
                "email": "created_by_attacker@test.com",
                "password": "Whatever!123",
                "userRole": UserRole.REGULAR,
                "userUserGroups": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_regular_cannot_delete_user(self):
        victim = create_regular_user(email="sec_deletable@test.com")
        self.authenticate_user(self.regular)
        url = reverse("UserViewSet-detail", kwargs={"uuid": victim.uuid})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_regular_user_list_does_not_leak_accounts(self):
        # Even read access must not expose the whole user table to a REGULAR user.
        create_super_admin(email="sec_other_admin@test.com")
        self.authenticate_user(self.regular)
        response = self.client.get(reverse("UserViewSet-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(_results(response), [])

    def test_super_admin_can_still_reset_password(self):
        # The fix must not break legitimate admin management.
        super_admin = create_super_admin(email="sec_realadmin@test.com")
        victim = create_regular_user(email="sec_managed@test.com", password="Old!12345")
        self.authenticate_user(super_admin)

        url = reverse("UserViewSet-detail", kwargs={"uuid": victim.uuid})
        response = self.client.patch(
            url,
            {
                "email": victim.email,
                "password": "NewByAdmin!123",
                "userRole": UserRole.REGULAR,
                "userUserGroups": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        victim.refresh_from_db()
        self.assertTrue(victim.check_password("NewByAdmin!123"))


class CustomActionWriteTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.regular = create_regular_user(email="sec_action_regular@test.com")

    def test_regular_cannot_run_management_command(self):
        # run-command `run` is a custom @action POST — previously reachable by anyone.
        self.authenticate_user(self.regular)
        response = self.client.post(
            reverse("CommandAsyncViewSet-run"),
            {"command": "import_custom_zones", "args": {}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_regular_cannot_bulk_create_tilesets(self):
        self.authenticate_user(self.regular)
        response = self.client.post(
            reverse("TileSetViewSet-bulk-create"), [], format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CustomZoneReadWriteSplitTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.regular = create_regular_user(email="sec_zone_regular@test.com")

    def test_regular_can_read_custom_zones(self):
        # Reads must keep working for regular users (the map relies on them).
        self.authenticate_user(self.regular)
        response = self.client.get(reverse("GeoCustomZoneViewSet-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_regular_cannot_create_custom_zone(self):
        self.authenticate_user(self.regular)
        response = self.client.post(
            reverse("GeoCustomZoneViewSet-list"),
            {"name": "attacker-zone"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class DeactivatedUserLockoutTests(BaseAPITestCase):
    def test_role_deactivated_user_is_denied_even_with_valid_token(self):
        # Deactivation via role does not flip is_active, so the JWT still authenticates.
        # IsActiveAuthenticated is what must lock the account out.
        user = create_regular_user(email="sec_deactivated@test.com")
        user.user_role = UserRole.DEACTIVATED
        user.save()
        self.authenticate_user(user)

        response = self.client.get(reverse("GeoCustomZoneViewSet-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
