import uuid

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_admin,
    create_regular_user,
    create_user_group,
    add_user_to_group,
)
from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneStatus,
    GeoCustomZoneType,
)
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from django.contrib.gis.geos import Polygon


def create_geo_custom_zone(name, category, geometry=None, color=None):
    if geometry is None:
        geometry = Polygon(
            [(3.8, 43.5), (3.9, 43.5), (3.9, 43.6), (3.8, 43.6), (3.8, 43.5)],
            srid=4326,
        )
    return GeoCustomZone.objects.create(
        name=name,
        geo_custom_zone_type=GeoCustomZoneType.COMMON,
        geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        geo_custom_zone_category=category,
        color=color or f"#{hash(name) % 0xFFFFFF:06x}",
        geometry=geometry,
    )


class GeoCustomZoneViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="gczadmin@test.com")
        self.admin = create_admin(email="gczmod@test.com")
        self.regular = create_regular_user(email="gczuser@test.com")
        self.category = GeoCustomZoneCategory.objects.create(
            name="Test Zone Cat", color="#112233", name_short="TZC"
        )
        self.zone_1 = create_geo_custom_zone(
            "Zone Alpha", self.category, color="#AA1122"
        )
        self.zone_2 = create_geo_custom_zone(
            "Zone Beta",
            self.category,
            color="#BB3344",
            geometry=Polygon(
                [(2.3, 48.8), (2.4, 48.8), (2.4, 48.9), (2.3, 48.9), (2.3, 48.8)],
                srid=4326,
            ),
        )

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("GeoCustomZoneViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 2)

    def test_list_unauthenticated(self):
        url = reverse("GeoCustomZoneViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "GeoCustomZoneViewSet-detail", kwargs={"uuid": str(self.zone_1.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Zone Alpha")

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.regular)
        url = reverse("GeoCustomZoneViewSet-detail", kwargs={"uuid": str(uuid.uuid4())})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_by_name(self):
        self.authenticate_user(self.regular)
        url = reverse("GeoCustomZoneViewSet-list")
        response = self.client.get(url, {"q": "Alpha"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in response.data]
        self.assertIn("Zone Alpha", names)

    def test_create_unauthenticated(self):
        url = reverse("GeoCustomZoneViewSet-list")
        data = {"name": "New Zone", "color": "#AABBCC"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_admin_with_user_group(self):
        group = create_user_group(name="Admin Group")
        group.geo_custom_zones.add(self.zone_1)
        add_user_to_group(self.admin, group)

        self.authenticate_user(self.admin)
        url = reverse("GeoCustomZoneViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        names = [r["name"] for r in response.data]
        self.assertIn("Zone Alpha", names)
        self.assertNotIn("Zone Beta", names)

    def test_list_admin_without_user_group(self):
        self.authenticate_user(self.admin)
        url = reverse("GeoCustomZoneViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_create_admin(self):
        group = create_user_group(name="Admin Create Group")
        add_user_to_group(self.admin, group)

        self.authenticate_user(self.admin)
        url = reverse("GeoCustomZoneViewSet-list")
        data = {"name": "Admin Zone", "color": "#CCDDEE"}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Admin Zone")
        self.assertTrue(group.geo_custom_zones.filter(name="Admin Zone").exists())

    def test_delete_unauthenticated(self):
        url = reverse(
            "GeoCustomZoneViewSet-detail", kwargs={"uuid": str(self.zone_2.uuid)}
        )
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
