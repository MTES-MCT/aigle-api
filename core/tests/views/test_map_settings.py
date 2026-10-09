from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import create_tile_set
from core.tests.fixtures.users import create_super_admin, create_regular_user


class MapSettingsViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="msadmin@test.com")
        self.regular = create_regular_user(email="msuser@test.com")

    def test_get_as_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("MapSettingsView")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_unauthenticated(self):
        url = reverse("MapSettingsView")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_not_allowed(self):
        self.authenticate_user(self.regular)
        url = reverse("MapSettingsView")
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_tile_sets_expose_shown_in_layers_panel(self):
        create_tile_set(name="Panel Shown")
        create_tile_set(name="Panel Hidden", shown_in_layers_panel=False)
        self.authenticate_user(self.super_admin)
        response = self.client.get(reverse("MapSettingsView"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tile_sets = [
            setting["tileSet"] for setting in response.json()["tileSetSettings"]
        ]
        self.assertTrue(tile_sets)
        for tile_set in tile_sets:
            self.assertIn("shownInLayersPanel", tile_set)
        shown_by_name = {
            tile_set["name"]: tile_set["shownInLayersPanel"] for tile_set in tile_sets
        }
        self.assertTrue(shown_by_name["Panel Shown"])
        self.assertFalse(shown_by_name["Panel Hidden"])
