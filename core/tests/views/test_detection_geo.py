from django.urls import reverse
from rest_framework import status

from core.models.detection import Detection
from core.models.geo_custom_zone import GeoCustomZone
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_super_admin, create_regular_user
from core.tests.fixtures.detection_data import (
    create_complete_detection_setup,
    create_object_type,
    create_tile,
    create_tile_set,
)
from core.tests.fixtures.geo_data import (
    create_complete_geo_hierarchy,
    create_montpellier_commune,
)


class DetectionGeoViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="dgadmin@test.com")
        self.regular = create_regular_user(email="dguser@test.com")
        self.geo_data = create_complete_geo_hierarchy()
        self.detection_setup = create_complete_detection_setup(
            commune=self.geo_data["communes"]["montpellier"],
        )
        self.custom_zone = GeoCustomZone.objects.create(
            name="Zone MTP",
            geometry=self.create_bbox_polygon(3.0, 43.0, 4.0, 44.0),
        )

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionGeoViewSet-list")
        response = self.client.get(
            url, {"customZonesUuids": str(self.custom_zone.uuid)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_without_custom_zones_returns_400(self):
        # at least one zone à enjeux must be selected — no urban-zone browsing
        self.authenticate_user(self.regular)
        url = reverse("DetectionGeoViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_unauthenticated(self):
        url = reverse("DetectionGeoViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_with_bbox_params(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionGeoViewSet-list")
        response = self.client.get(
            url,
            {
                "neLat": 44.0,
                "neLng": 4.0,
                "swLat": 43.0,
                "swLng": 3.0,
                "customZonesUuids": str(self.custom_zone.uuid),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class DetectionCreateCustomZoneTests(BaseAPITestCase):
    """A detection cannot be created outside every accessible custom zone (zone urbaine)."""

    RING = [
        [3.8799, 43.6099],
        [3.8801, 43.6099],
        [3.8801, 43.6101],
        [3.8799, 43.6101],
        [3.8799, 43.6099],
    ]

    def setUp(self):
        super().setUp()
        self.user = create_super_admin(email="createzone@test.com")
        self.authenticate_user(self.user)
        self.commune = create_montpellier_commune()
        self.object_type = create_object_type()
        self.tile_set = create_tile_set(name="Create MTP 2024")
        self.tile_set.geo_zones.add(self.commune)
        self.url = reverse("DetectionGeoViewSet-list")

    def _post(self):
        return self.client.post(
            self.url,
            {
                "geometry": {"type": "Polygon", "coordinates": [self.RING]},
                "tileSetUuid": str(self.tile_set.uuid),
                "detectionObject": {"objectTypeUuid": str(self.object_type.uuid)},
            },
            format="json",
        )

    def test_create_blocked_outside_custom_zone(self):
        response = self._post()  # no custom zone -> zone urbaine
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_allowed_inside_custom_zone(self):
        # z19 slippy tile containing the geometry centroid (~3.88, 43.61)
        create_tile(x=267794, y=191428, z=19)
        GeoCustomZone.objects.create(
            name="Create covering",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.89, 43.62),
        )
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_allowed_when_covered_by_union_of_zones(self):
        # The RING (lng 3.8799..3.8801) straddles the shared edge at lng=3.88 of two
        # edge-adjacent zones: covered by their union, by neither single zone. Must be
        # allowed, and created WITH NO custom zone associated (association is single-zone).
        create_tile(x=267794, y=191428, z=19)
        GeoCustomZone.objects.create(
            name="Left half",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.88, 43.62),
        )
        GeoCustomZone.objects.create(
            name="Right half",
            geometry=self.create_bbox_polygon(3.88, 43.60, 3.89, 43.62),
        )
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        detection = Detection.objects.order_by("-id").first()
        self.assertEqual(detection.detection_object.geo_custom_zones.count(), 0)

    def test_create_blocked_when_only_partially_covered(self):
        # A single zone covering only the western part leaves the eastern part urban:
        # union does not cover the RING -> blocked.
        create_tile(x=267794, y=191428, z=19)
        GeoCustomZone.objects.create(
            name="West only",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.88, 43.62),
        )
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
