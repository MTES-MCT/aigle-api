import uuid

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_admin,
    create_regular_user,
    create_user_group,
)


class UserGroupViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="ugadmin@test.com")
        self.admin = create_admin(email="ugmod@test.com")
        self.regular = create_regular_user(email="uguser@test.com")
        self.group_1 = create_user_group(name="DDTM Hérault")
        self.group_2 = create_user_group(name="Collectivité Montpellier")

    def test_list_as_super_admin(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 2)

    def test_list_unauthenticated(self):
        url = reverse("UserGroupViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.super_admin)
        url = reverse(
            "UserGroupViewSet-detail", kwargs={"uuid": str(self.group_1.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "DDTM Hérault")

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-detail", kwargs={"uuid": str(uuid.uuid4())})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_by_name(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-list")
        response = self.client.get(url, {"q": "Hérault"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in response.data]
        self.assertIn("DDTM Hérault", names)

    def test_create_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse("UserGroupViewSet-list")
        data = {"name": "New Group"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "UserGroupViewSet-detail", kwargs={"uuid": str(self.group_2.uuid)}
        )
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
