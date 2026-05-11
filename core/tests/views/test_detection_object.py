import uuid
from datetime import datetime

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import create_regular_user
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
