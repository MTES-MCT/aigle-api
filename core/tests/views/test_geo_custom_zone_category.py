import uuid

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_super_admin, create_regular_user
from core.models.geo_custom_zone_category import GeoCustomZoneCategory


def create_geo_custom_zone_category(name, color, name_short=None):
    return GeoCustomZoneCategory.objects.create(
        name=name,
        color=color,
        name_short=name_short or name[:10],
    )


class GeoCustomZoneCategoryViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="gczcadmin@test.com")
        self.regular = create_regular_user(email="gczcuser@test.com")
        self.category_1 = create_geo_custom_zone_category(
            name="Zone Naturelle", color="#00FF00", name_short="ZN"
        )
        self.category_2 = create_geo_custom_zone_category(
            name="Zone Agricole", color="#FF0000", name_short="ZA"
        )

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("GeoCustomZoneCategoryViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 2)

    def test_list_unauthenticated(self):
        url = reverse("GeoCustomZoneCategoryViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "GeoCustomZoneCategoryViewSet-detail",
            kwargs={"uuid": str(self.category_1.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Zone Naturelle")

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "GeoCustomZoneCategoryViewSet-detail", kwargs={"uuid": str(uuid.uuid4())}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_by_name(self):
        self.authenticate_user(self.regular)
        url = reverse("GeoCustomZoneCategoryViewSet-list")
        response = self.client.get(url, {"q": "Naturelle"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in response.data]
        self.assertIn("Zone Naturelle", names)

    def test_create_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse("GeoCustomZoneCategoryViewSet-list")
        data = {"name": "New Category", "color": "#AABBCC", "name_short": "NC"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "GeoCustomZoneCategoryViewSet-detail",
            kwargs={"uuid": str(self.category_2.uuid)},
        )
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
