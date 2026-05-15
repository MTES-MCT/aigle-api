from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_regular_user,
    create_user_group,
    add_user_to_group,
)
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy


class ParcelViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="parcadmin@test.com")
        self.regular = create_regular_user(email="parcuser@test.com")
        self.geo_data = create_complete_geo_hierarchy()
        self.parcels = self.geo_data["parcels"]
        group = create_user_group(
            name="Test Parcel Group",
            geo_zones=[self.geo_data["departments"]["herault"]],
        )
        add_user_to_group(self.regular, group)
        add_user_to_group(self.super_admin, group)

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("ParcelViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_unauthenticated(self):
        url = reverse("ParcelViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.regular)
        parcel = self.parcels[0]
        url = reverse("ParcelViewSet-detail", kwargs={"uuid": str(parcel.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
