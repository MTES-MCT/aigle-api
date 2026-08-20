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


def create_geo_custom_zone(name, category, geometry=None, color=None, description=None):
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
        description=description,
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

    def test_partial_update_keeps_active_when_geometry_present(self):
        # Regression: PATCHing a zone that already has a geometry must not load
        # the (deferred, potentially department-sized) geometry into memory and
        # must keep the zone ACTIVE. See GeoCustomZoneInputSerializer.update.
        self.authenticate_user(self.super_admin)
        url = reverse(
            "GeoCustomZoneViewSet-detail", kwargs={"uuid": str(self.zone_1.uuid)}
        )
        response = self.client.patch(
            url,
            {
                "name": "Zone Alpha renamed",
                "geoCustomZoneCategoryUuid": str(self.category.uuid),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.zone_1.refresh_from_db()
        self.assertEqual(self.zone_1.name, "Zone Alpha renamed")
        self.assertEqual(self.zone_1.geo_custom_zone_status, GeoCustomZoneStatus.ACTIVE)
        self.assertIsNotNone(self.zone_1.geometry)

    def test_retrieve_returns_description(self):
        zone = create_geo_custom_zone(
            "Zone Described",
            self.category,
            color="#DD5566",
            description="Texte indicatif sur la couche",
        )
        self.authenticate_user(self.regular)
        url = reverse("GeoCustomZoneViewSet-detail", kwargs={"uuid": str(zone.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["description"], "Texte indicatif sur la couche")

    def test_retrieve_description_is_none_when_unset(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "GeoCustomZoneViewSet-detail", kwargs={"uuid": str(self.zone_1.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["description"])

    def test_partial_update_sets_description(self):
        self.authenticate_user(self.super_admin)
        url = reverse(
            "GeoCustomZoneViewSet-detail", kwargs={"uuid": str(self.zone_1.uuid)}
        )
        response = self.client.patch(
            url,
            {
                "description": "Texte indicatif sur la couche si nécessaire.",
                "geoCustomZoneCategoryUuid": str(self.category.uuid),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["description"], "Texte indicatif sur la couche si nécessaire."
        )
        self.zone_1.refresh_from_db()
        self.assertEqual(
            self.zone_1.description, "Texte indicatif sur la couche si nécessaire."
        )

    def test_partial_update_sets_inactive_when_geometry_missing(self):
        zone_no_geometry = GeoCustomZone.objects.create(
            name="Zone Without Geometry",
            geo_custom_zone_type=GeoCustomZoneType.COMMON,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
            geo_custom_zone_category=self.category,
            color="#CC5566",
            geometry=None,
        )
        self.authenticate_user(self.super_admin)
        url = reverse(
            "GeoCustomZoneViewSet-detail", kwargs={"uuid": str(zone_no_geometry.uuid)}
        )
        response = self.client.patch(
            url,
            {
                "name": "Zone Without Geometry renamed",
                "geoCustomZoneCategoryUuid": str(self.category.uuid),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        zone_no_geometry.refresh_from_db()
        self.assertEqual(
            zone_no_geometry.geo_custom_zone_status, GeoCustomZoneStatus.INACTIVE
        )


class GeoCustomZoneManagerTests(BaseAPITestCase):
    """The centralized `.active()` idiom: display reads use it to drop deactivated zones;
    plain `objects` (and the M2M related manager's `.all()`) still see every status so
    admin/import/reactivation code keeps working."""

    def setUp(self):
        super().setUp()
        self.category = GeoCustomZoneCategory.objects.create(
            name="Mgr Cat", color="#334455", name_short="MC"
        )
        self.active_zone = create_geo_custom_zone(
            "Mgr Active", self.category, color="#0A0A0A"
        )
        self.inactive_zone = create_geo_custom_zone(
            "Mgr Inactive", self.category, color="#0B0B0B"
        )
        self.inactive_zone.geo_custom_zone_status = GeoCustomZoneStatus.INACTIVE
        self.inactive_zone.save()

    def test_objects_active_excludes_inactive(self):
        names = set(GeoCustomZone.objects.active().values_list("name", flat=True))
        self.assertIn("Mgr Active", names)
        self.assertNotIn("Mgr Inactive", names)

    def test_objects_default_keeps_all_statuses(self):
        # Admin/management must still reach deactivated zones through plain `objects`.
        names = set(GeoCustomZone.objects.values_list("name", flat=True))
        self.assertIn("Mgr Active", names)
        self.assertIn("Mgr Inactive", names)

    def test_active_is_available_on_m2m_related_manager(self):
        from core.tests.fixtures.detection_data import create_detection_object

        detection_object = create_detection_object()
        detection_object.geo_custom_zones.add(self.active_zone, self.inactive_zone)

        active_names = set(
            detection_object.geo_custom_zones.active().values_list("name", flat=True)
        )
        self.assertEqual(active_names, {"Mgr Active"})
        # the relation itself still exposes both (write/read-back stays complete)
        self.assertEqual(detection_object.geo_custom_zones.count(), 2)

    def test_active_defers_geometry(self):
        # `.active()` must keep GeoZoneManager's geometry deferral.
        zone = GeoCustomZone.objects.active().get(pk=self.active_zone.pk)
        self.assertIn("geometry", zone.get_deferred_fields())
