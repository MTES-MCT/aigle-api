import uuid
from datetime import datetime

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from core.models.geo_custom_zone import GeoCustomZone
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import (
    add_user_to_group,
    create_regular_user,
    create_super_admin,
    create_user_group,
)
from core.tests.fixtures.detection_data import (
    create_complete_detection_setup,
    create_detection_with_object,
    create_tile_set,
)


class DetectionObjectViewSetTests(BaseAPITestCase):
    def _get_results(self, response):
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]
        return response.data

    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        self.parcels = self.geo_data["parcels"]

        self.detection_setup = create_complete_detection_setup(parcel=self.parcels[0])
        self.detection_object = self.detection_setup["detection_object"]
        self.detection = self.detection_setup["detection"]
        self.tile_set = self.detection_setup["tile_set"]

        self.user = create_regular_user()
        self.authenticate_user(self.user)

    def test_list_detection_objects_authenticated(self):
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(self._get_results(response), list)
        self.assertGreater(len(self._get_results(response)), 0)

    def test_list_detection_objects_unauthenticated(self):
        self.unauthenticate()
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_detection_object_detail(self):
        url = reverse(
            "DetectionObjectViewSet-detail",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["uuid"], str(self.detection_object.uuid))

    def test_filter_detection_objects_by_uuids(self):
        detection_object_2, _ = create_detection_with_object(
            x=3.89, y=43.62, object_type_name="Building"
        )

        url = reverse("DetectionObjectViewSet-list")
        uuids = f"{self.detection_object.uuid},{detection_object_2.uuid}"
        response = self.client.get(url, {"uuids": uuids})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        self.assertGreaterEqual(len(results), 2)

        result_uuids = [r["uuid"] for r in results]
        self.assertIn(str(self.detection_object.uuid), result_uuids)
        self.assertIn(str(detection_object_2.uuid), result_uuids)

    def test_filter_detection_objects_by_detection_uuids(self):
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url, {"detectionUuids": str(self.detection.uuid)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        self.assertGreater(len(results), 0)

        result_uuids = [r["uuid"] for r in results]
        self.assertIn(str(self.detection_object.uuid), result_uuids)

    def test_get_from_coordinates_missing_params(self):
        url = reverse("DetectionObjectViewSet-get-from-coordinates")

        response = self.client.get(url, {"lat": 43.61})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(url, {"lng": 3.88})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_history_action(self):
        url = reverse(
            "DetectionObjectViewSet-history",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_detection_object_includes_object_type(self):
        url = reverse(
            "DetectionObjectViewSet-detail",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        has_object_type = (
            "objectType" in response.data or "object_type" in response.data
        )
        self.assertTrue(has_object_type)

    def test_detection_object_with_detail_param(self):
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url, {"detail": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_nonexistent_detection_object_returns_404(self):
        fake_uuid = uuid.uuid4()
        url = reverse("DetectionObjectViewSet-detail", kwargs={"uuid": str(fake_uuid)})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_detection_object_ordering(self):
        tile_set_old = create_tile_set(
            name="Old TileSet",
            date=timezone.make_aware(datetime(2020, 1, 1)),
        )
        tile_set_new = create_tile_set(
            name="New TileSet",
            date=timezone.make_aware(datetime(2024, 1, 1)),
        )

        old_obj, _ = create_detection_with_object(
            x=3.87,
            y=43.60,
            tile_set=tile_set_old,
            object_type_name="Old Detection Type",
        )
        new_obj, _ = create_detection_with_object(
            x=3.89,
            y=43.62,
            tile_set=tile_set_new,
            object_type_name="New Detection Type",
        )

        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)

        if len(results) >= 2:
            uuids = [r["uuid"] for r in results]
            new_obj_index = next(
                (i for i, u in enumerate(uuids) if u == str(new_obj.uuid)), None
            )
            old_obj_index = next(
                (i for i, u in enumerate(uuids) if u == str(old_obj.uuid)), None
            )

            if new_obj_index is not None and old_obj_index is not None:
                self.assertLess(new_obj_index, old_obj_index)


class FromCoordinatesCustomZoneTests(BaseAPITestCase):
    """A point outside every accessible custom zone (zone urbaine) cannot be searched."""

    def setUp(self):
        super().setUp()
        self.user = create_super_admin(email="fromcoord@test.com")
        self.authenticate_user(self.user)
        self.url = reverse("DetectionObjectViewSet-get-from-coordinates")

    def _is_urban_block(self, response):
        return (
            response.status_code == status.HTTP_403_FORBIDDEN
            and isinstance(response.data, dict)
            and response.data.get("code") == "OUTSIDE_CUSTOM_ZONE"
        )

    def test_returns_outside_custom_zone_in_urban_area(self):
        # an active zone exists elsewhere, but the queried point is covered by none
        GeoCustomZone.objects.create(
            name="Elsewhere",
            geometry=self.create_bbox_polygon(4.10, 43.60, 4.12, 43.62),
        )
        response = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertTrue(self._is_urban_block(response))

    def test_no_active_zone_anywhere_blocks_search(self):
        response = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertTrue(self._is_urban_block(response))

    def test_point_inside_custom_zone_is_not_blocked_as_urban(self):
        GeoCustomZone.objects.create(
            name="Covering",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.89, 43.62),
        )
        response = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        # passes the custom-zone gate; downstream may 403 (no tile set) or 200/null,
        # but it must NOT be the urban block.
        self.assertFalse(self._is_urban_block(response))

    def test_inactive_covering_zone_still_blocks(self):
        GeoCustomZone.objects.create(
            name="Inactive covering",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.89, 43.62),
            geo_custom_zone_status="INACTIVE",
        )
        response = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertTrue(self._is_urban_block(response))

    def test_scoped_to_user_groups_custom_zones(self):
        # The covering zone is real and active, but a regular user only reaches it if
        # one of their user groups grants it — the heart of "accessible by the user".
        covering_zone = GeoCustomZone.objects.create(
            name="Group covering",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.89, 43.62),
        )
        with_access = create_regular_user(email="withzone@test.com")
        group = create_user_group(name="Zone group")
        group.geo_custom_zones.add(covering_zone)
        add_user_to_group(with_access, group)

        without_access = create_regular_user(email="nozone@test.com")

        self.authenticate_user(without_access)
        blocked = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertTrue(self._is_urban_block(blocked))

        self.authenticate_user(with_access)
        allowed = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertFalse(self._is_urban_block(allowed))
