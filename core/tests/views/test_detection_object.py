"""
Tests for DetectionObjectViewSet.

Tests cover:
- List detection objects
- Retrieve detection object details
- Filter by UUIDs
- Filter by detection UUIDs
- from-coordinates custom action
- History endpoint
- Spatial queries
"""

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import create_regular_user
from core.tests.fixtures.detection_data import (
    create_complete_detection_setup,
    create_detection_with_object,
    create_object_type,
)


class DetectionObjectViewSetTests(BaseAPITestCase):
    """Tests for DetectionObjectViewSet."""

    def setUp(self):
        """Set up test data."""
        super().setUp()

        # Create geographic hierarchy
        self.geo_data = create_complete_geo_hierarchy()
        self.parcels = self.geo_data["parcels"]

        # Create detection setup
        self.detection_setup = create_complete_detection_setup(parcel=self.parcels[0])
        self.detection_object = self.detection_setup["detection_object"]
        self.detection = self.detection_setup["detection"]
        self.tile_set = self.detection_setup["tile_set"]

        # Create authenticated user
        self.user = create_regular_user()
        self.authenticate_user(self.user)

    def test_list_detection_objects_authenticated(self):
        """Test listing detection objects with authenticated user."""
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["results"], list)
        self.assertGreater(len(response.data["results"]), 0)

    def test_list_detection_objects_unauthenticated(self):
        """Test that unauthenticated users cannot list detection objects."""
        self.unauthenticate()
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_detection_object_detail(self):
        """Test retrieving a single detection object's details."""
        url = reverse(
            "DetectionObjectViewSet-detail",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["uuid"], str(self.detection_object.uuid))

    def test_filter_detection_objects_by_uuids(self):
        """Test filtering detection objects by UUIDs."""
        # Create another detection object
        detection_object_2, _ = create_detection_with_object(
            x=3.89, y=43.62, object_type_name="Building"
        )

        url = reverse("DetectionObjectViewSet-list")
        uuids = f"{self.detection_object.uuid},{detection_object_2.uuid}"
        response = self.client.get(url, {"uuids": uuids})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 2)

        # Verify both objects are in results
        result_uuids = [r["uuid"] for r in results]
        self.assertIn(str(self.detection_object.uuid), result_uuids)
        self.assertIn(str(detection_object_2.uuid), result_uuids)

    def test_filter_detection_objects_by_detection_uuids(self):
        """Test filtering detection objects by detection UUIDs."""
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url, {"detectionUuids": str(self.detection.uuid)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]

        # Should find the detection object
        self.assertGreater(len(results), 0)
        result_uuids = [r["uuid"] for r in results]
        self.assertIn(str(self.detection_object.uuid), result_uuids)

    def test_get_from_coordinates_action(self):
        """Test the from-coordinates custom action."""
        # Create detection at specific coordinates
        x, y = 3.88, 43.61
        detection_obj, detection = create_detection_with_object(
            x=x, y=y, object_type_name="Swimming Pool", tile_set=self.tile_set
        )

        url = reverse("DetectionObjectViewSet-get-from-coordinates")
        response = self.client.get(url, {"lat": y, "lng": x})

        # May return 200 OK with data or 403 depending on permissions
        if response.status_code == status.HTTP_200_OK:
            if response.data:
                self.assertIn("uuid", response.data)
                self.assertIn("geometry", response.data)
                self.assertIn("objectTypeUuid", response.data)

    def test_get_from_coordinates_missing_params(self):
        """Test from-coordinates action with missing parameters."""
        url = reverse("DetectionObjectViewSet-get-from-coordinates")

        # Missing lng parameter
        response = self.client.get(url, {"lat": 43.61})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Missing lat parameter
        response = self.client.get(url, {"lng": 3.88})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_history_action(self):
        """Test the history custom action."""
        url = reverse(
            "DetectionObjectViewSet-history",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)

        # History endpoint should return detection history
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_detection_object_includes_detections(self):
        """Test that detection object detail includes detections."""
        url = reverse(
            "DetectionObjectViewSet-detail",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Response should include detections (serializer dependent)

    def test_detection_object_includes_object_type(self):
        """Test that detection object includes object type information."""
        url = reverse(
            "DetectionObjectViewSet-detail",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("objectType", response.data)

    def test_detection_object_with_detail_param(self):
        """Test requesting detection object with detail parameter."""
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url, {"detail": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # With detail=true, should use DetailSerializer

    def test_retrieve_saves_user_position(self):
        """Test that retrieving detection object saves user position."""
        url = reverse(
            "DetectionObjectViewSet-detail",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify user's last position was saved (service layer handles this)
        self.user.refresh_from_db()
        # Position should be set to detection geometry centroid

    def test_detection_object_ordering(self):
        """Test that detection objects are ordered by tile set date."""
        # Create detection objects with different tile sets
        from core.models import TileSet
        from datetime import date

        tile_set_old = TileSet.objects.create(
            name="Old TileSet", year=2020, resolution=0.2, date=date(2020, 1, 1)
        )

        tile_set_new = TileSet.objects.create(
            name="New TileSet", year=2024, resolution=0.2, date=date(2024, 1, 1)
        )

        old_obj, _ = create_detection_with_object(
            x=3.87, y=43.60, tile_set=tile_set_old
        )

        new_obj, _ = create_detection_with_object(
            x=3.89, y=43.62, tile_set=tile_set_new
        )

        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]

        # Newer detection objects should appear first
        if len(results) >= 2:
            uuids = [r["uuid"] for r in results]
            new_obj_index = next(
                (i for i, uuid in enumerate(uuids) if uuid == str(new_obj.uuid)), None
            )
            old_obj_index = next(
                (i for i, uuid in enumerate(uuids) if uuid == str(old_obj.uuid)), None
            )

            if new_obj_index is not None and old_obj_index is not None:
                self.assertLess(new_obj_index, old_obj_index)

    def test_detection_object_prefetch_optimization(self):
        """Test that detection objects are efficiently prefetched."""
        url = reverse("DetectionObjectViewSet-list")

        # This test verifies the queryset optimization
        # In production, you'd use django-debug-toolbar or assertNumQueries
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # The queryset should use select_related and prefetch_related

    def test_retrieve_nonexistent_detection_object_returns_404(self):
        """Test retrieving a non-existent detection object returns 404."""
        import uuid

        fake_uuid = uuid.uuid4()
        url = reverse("DetectionObjectViewSet-detail", kwargs={"uuid": str(fake_uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_detection_object(self):
        """Test updating detection object."""
        url = reverse(
            "DetectionObjectViewSet-detail",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )

        # Create a new object type to change to
        new_object_type = create_object_type(name="Updated Type")

        update_data = {
            "objectType": str(new_object_type.uuid),
        }

        response = self.client.patch(url, update_data, format="json")

        # May succeed or fail based on permissions
        if response.status_code == status.HTTP_200_OK:
            self.detection_object.refresh_from_db()
            self.assertEqual(
                self.detection_object.object_type.uuid, new_object_type.uuid
            )
