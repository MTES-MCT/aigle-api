import uuid

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import create_super_admin, create_regular_user


class GeoDepartmentViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        self.herault = self.geo_data["departments"]["herault"]
        self.paris = self.geo_data["departments"]["paris"]
        self.super_admin = create_super_admin(email="deptadmin@test.com")
        self.regular = create_regular_user(email="deptuser@test.com")

    def test_list_authenticated(self):
        self.authenticate_user(self.super_admin)
        url = reverse("GeoDepartmentViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 4)

    def test_list_unauthenticated(self):
        url = reverse("GeoDepartmentViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.super_admin)
        url = reverse(
            "GeoDepartmentViewSet-detail", kwargs={"uuid": str(self.herault.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Hérault")
        self.assertEqual(response.data["code"], "34")

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.super_admin)
        url = reverse("GeoDepartmentViewSet-detail", kwargs={"uuid": str(uuid.uuid4())})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_by_name(self):
        self.authenticate_user(self.super_admin)
        url = reverse("GeoDepartmentViewSet-list")
        response = self.client.get(url, {"q": "Hérault"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in response.data]
        self.assertIn("Hérault", names)

    def test_search_by_code(self):
        self.authenticate_user(self.super_admin)
        url = reverse("GeoDepartmentViewSet-list")
        response = self.client.get(url, {"q": "34"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data), 0)

    def test_regular_user_can_list(self):
        self.authenticate_user(self.regular)
        url = reverse("GeoDepartmentViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
