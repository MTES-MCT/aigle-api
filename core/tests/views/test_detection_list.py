import csv
import io

from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_regular_user,
    create_user_group,
    add_user_to_group,
)
from core.tests.fixtures.detection_data import (
    create_complete_detection_setup,
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type,
    create_tile_set,
)
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy


class DetectionListViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="dladmin@test.com")
        self.regular = create_regular_user(email="dluser@test.com")
        self.geo_data = create_complete_geo_hierarchy()
        self.detection_setup = create_complete_detection_setup(
            commune=self.geo_data["communes"]["montpellier"],
        )
        group = create_user_group(
            name="Test DL Group",
            geo_zones=[self.geo_data["departments"]["herault"]],
        )
        add_user_to_group(self.regular, group)
        add_user_to_group(self.super_admin, group)
        self.custom_zone = GeoCustomZone.objects.create(
            name="Zone DL",
            geometry=self.create_bbox_polygon(3.0, 43.0, 4.0, 44.0),
        )

    def test_list_unauthenticated(self):
        url = reverse("DetectionListViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionListViewSet-list")
        response = self.client.get(
            url, {"customZonesUuids": str(self.custom_zone.uuid)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_without_custom_zones_returns_400(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionListViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_download_excludes_deactivated_custom_zones(self):
        # Regression: the CSV/XLSX export "Zones à enjeux" column is built from a
        # separate Subquery annotation that bypassed the ACTIVE-filtered prefetch, so
        # deactivated zones leaked into the downloaded file.
        self.authenticate_user(self.super_admin)

        tile_set = create_tile_set(name="DL TileSet 2024")
        tile_set.geo_zones.add(self.geo_data["departments"]["herault"])

        object_type = create_object_type(name="Cabane DL")
        detection_object = create_detection_object(
            object_type=object_type,
            commune=self.geo_data["communes"]["montpellier"],
        )
        detection_data = create_detection_data(
            detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
            detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
        )
        create_detection(
            detection_object=detection_object,
            tile_set=tile_set,
            geometry=Point(3.88, 43.61, srid=4326),
            score=0.95,
            detection_data=detection_data,
        )

        active_zone = GeoCustomZone.objects.create(
            name="Active DL enjeux",
            geometry=self.create_bbox_polygon(3.0, 43.0, 4.0, 44.0),
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        )
        inactive_zone = GeoCustomZone.objects.create(
            name="Deactivated DL enjeux",
            geometry=self.create_bbox_polygon(3.0, 43.0, 4.0, 44.0),
            geo_custom_zone_status=GeoCustomZoneStatus.INACTIVE,
        )
        detection_object.geo_custom_zones.add(active_zone, inactive_zone)

        url = reverse("DetectionListViewSet-download")
        response = self.client.get(
            url,
            {"customZonesUuids": str(active_zone.uuid), "outputFormat": "csv"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
        zones_index = rows[0].index("Zones à enjeux")
        zone_cells = [row[zones_index] for row in rows[1:]]

        self.assertTrue(any("Active DL enjeux" in cell for cell in zone_cells))
        self.assertFalse(any("Deactivated DL enjeux" in cell for cell in zone_cells))
