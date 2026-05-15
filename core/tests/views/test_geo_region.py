import uuid

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import create_super_admin, create_regular_user


class GeoRegionViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        self.occitanie = self.geo_data["regions"]["occitanie"]
        self.ile_de_france = self.geo_data["regions"]["ile_de_france"]
        self.super_admin = create_super_admin(email="regionadmin@test.com")
        self.regular = create_regular_user(email="regionuser@test.com")

    def test_list_authenticated(self):
        self.authenticate_user(self.super_admin)
        url = reverse("GeoRegionViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 2)

    def test_list_unauthenticated(self):
        url = reverse("GeoRegionViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.super_admin)
        url = reverse(
            "GeoRegionViewSet-detail", kwargs={"uuid": str(self.occitanie.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Occitanie")
        self.assertEqual(response.data["code"], "76")

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.super_admin)
        url = reverse("GeoRegionViewSet-detail", kwargs={"uuid": str(uuid.uuid4())})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_by_name(self):
        self.authenticate_user(self.super_admin)
        url = reverse("GeoRegionViewSet-list")
        response = self.client.get(url, {"q": "Occitanie"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in response.data]
        self.assertIn("Occitanie", names)

    def test_search_by_code(self):
        self.authenticate_user(self.super_admin)
        url = reverse("GeoRegionViewSet-list")
        response = self.client.get(url, {"q": "76"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data), 0)

    def test_search_case_insensitive(self):
        self.authenticate_user(self.super_admin)
        url = reverse("GeoRegionViewSet-list")
        response = self.client.get(url, {"q": "occitanie"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in response.data]
        self.assertIn("Occitanie", names)

    def test_regular_user_can_list(self):
        self.authenticate_user(self.regular)
        url = reverse("GeoRegionViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
