from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_regular_user,
    create_user_group,
    add_user_to_group,
)
from core.tests.fixtures.detection_data import create_tile_set
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy


class StatisticsViewsTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="statsadmin@test.com")
        self.regular = create_regular_user(email="statsuser@test.com")
        self.geo_data = create_complete_geo_hierarchy()
        self.tile_set = create_tile_set(name="Stats TileSet")

        group = create_user_group(
            name="Stats Group",
            geo_zones=[self.geo_data["departments"]["herault"]],
        )
        add_user_to_group(self.regular, group)
        add_user_to_group(self.super_admin, group)

    def _stats_params(self):
        return {"tileSetsUuids": str(self.tile_set.uuid)}

    def test_validation_status_global_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("StatisticsValidationStatusGlobalView")
        response = self.client.get(url, self._stats_params())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_validation_status_global_unauthenticated(self):
        url = reverse("StatisticsValidationStatusGlobalView")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_validation_status_evolution_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("StatisticsValidationStatusEvolutionView")
        response = self.client.get(url, self._stats_params())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_validation_status_evolution_unauthenticated(self):
        url = reverse("StatisticsValidationStatusEvolutionView")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_validation_status_object_types_global_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("StatisticsValidationStatusObjectTypesGlobalView")
        response = self.client.get(url, self._stats_params())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_validation_status_object_types_global_unauthenticated(self):
        url = reverse("StatisticsValidationStatusObjectTypesGlobalView")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
