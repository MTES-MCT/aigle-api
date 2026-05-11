from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_super_admin, create_regular_user
from core.tests.fixtures.detection_data import create_complete_detection_setup
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy


class DetectionGeoViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="dgadmin@test.com")
        self.regular = create_regular_user(email="dguser@test.com")
        self.geo_data = create_complete_geo_hierarchy()
        self.detection_setup = create_complete_detection_setup(
            commune=self.geo_data["communes"]["montpellier"],
        )

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionGeoViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

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
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
