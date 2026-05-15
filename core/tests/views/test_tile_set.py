import uuid

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_super_admin, create_regular_user
from core.tests.fixtures.detection_data import create_tile_set


class TileSetViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="tsadmin@test.com")
        self.regular = create_regular_user(email="tsuser@test.com")
        self.tile_set_1 = create_tile_set(name="Montpellier 2024")
        self.tile_set_2 = create_tile_set(name="Paris 2023")

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("TileSetViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 2)

    def test_list_unauthenticated(self):
        url = reverse("TileSetViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "TileSetViewSet-detail", kwargs={"uuid": str(self.tile_set_1.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Montpellier 2024")

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.regular)
        url = reverse("TileSetViewSet-detail", kwargs={"uuid": str(uuid.uuid4())})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse("TileSetViewSet-list")
        data = {
            "name": "New TileSet",
            "url": "https://example.com/tiles/new",
            "date": "2024-01-01",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "TileSetViewSet-detail", kwargs={"uuid": str(self.tile_set_2.uuid)}
        )
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_search_by_name(self):
        self.authenticate_user(self.regular)
        url = reverse("TileSetViewSet-list")
        response = self.client.get(url, {"q": "Montpellier"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in response.data]
        self.assertIn("Montpellier 2024", names)
