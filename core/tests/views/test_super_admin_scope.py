from django.urls import reverse
from rest_framework import status

from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.user_group import UserGroupType
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_object_type_category,
    create_object_type_with_category,
    create_tile_set,
)
from core.tests.fixtures.geo_data import (
    create_herault_department,
    create_montpellier_commune,
    create_occitanie_region,
)
from core.tests.fixtures.users import (
    create_regular_user,
    create_super_admin,
    create_user_group,
    add_user_to_group,
)


class SuperAdminScopeMapSettingsTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-sa@test.com")
        self.regular_user = create_regular_user(email="scope-reg@test.com")

        self.region = create_occitanie_region()
        self.dept = create_herault_department(region=self.region)
        self.commune = create_montpellier_commune(department=self.dept)

        self.category = create_object_type_category(name="Scope Cat")
        create_object_type_with_category(
            object_type_name="Scope ObjType",
            category_name="Scope Cat",
        )

        self.group_a = create_user_group(name="Group A", geo_zones=[self.dept])
        self.group_a.object_type_categories.add(self.category)
        self.group_a.user_group_type = UserGroupType.DDTM
        self.group_a.save()

        self.group_b = create_user_group(name="Group B")
        self.group_b.user_group_type = UserGroupType.COLLECTIVITY
        self.group_b.save()

        self.tile_set = create_tile_set(name="Scope TS")
        self.tile_set.geo_zones.add(self.dept)

        self.url = reverse("MapSettingsView")

    def test_map_settings_without_scope_returns_all(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tile_names = [
            ts["tile_set"]["name"] for ts in response.data["tile_set_settings"]
        ]
        self.assertIn("Scope TS", tile_names)

    def test_map_settings_with_scope_returns_scoped_data(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            self.url,
            HTTP_X_USER_GROUP_UUID=str(self.group_a.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tile_names = [
            ts["tile_set"]["name"] for ts in response.data["tile_set_settings"]
        ]
        self.assertIn("Scope TS", tile_names)

    def test_map_settings_with_scope_filters_object_types(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            self.url,
            HTTP_X_USER_GROUP_UUID=str(self.group_a.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        obj_type_names = [
            ot["object_type"]["name"] for ot in response.data["object_type_settings"]
        ]
        self.assertIn("Scope ObjType", obj_type_names)

    def test_map_settings_scope_filters_tiles_by_group_geo_zones(self):
        from core.tests.fixtures.geo_data import (
            create_ile_de_france_region,
            create_paris_department,
        )

        other_dept = create_paris_department(region=create_ile_de_france_region())
        other_ts = create_tile_set(name="Other TS")
        other_ts.geo_zones.add(other_dept)

        group_c = create_user_group(name="Group C", geo_zones=[other_dept])

        self.authenticate_user(self.super_admin)
        response = self.client.get(
            self.url,
            HTTP_X_USER_GROUP_UUID=str(group_c.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tile_names = [
            ts["tile_set"]["name"] for ts in response.data["tile_set_settings"]
        ]
        self.assertIn("Other TS", tile_names)
        self.assertNotIn("Scope TS", tile_names)

    def test_map_settings_scoped_to_empty_group_returns_no_object_types(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            self.url,
            HTTP_X_USER_GROUP_UUID=str(self.group_b.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["object_type_settings"]), 0)

    def test_regular_user_cannot_use_scope_header(self):
        add_user_to_group(self.regular_user, self.group_a)
        self.authenticate_user(self.regular_user)
        response = self.client.get(
            self.url,
            HTTP_X_USER_GROUP_UUID=str(self.group_a.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_group_uuid_returns_400(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            self.url,
            HTTP_X_USER_GROUP_UUID="00000000-0000-0000-0000-000000000000",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_header_means_no_scoping(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["tile_set_settings"])


class SuperAdminScopeCustomZonesTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-cz-sa@test.com")

        self.region = create_occitanie_region()
        self.dept = create_herault_department(region=self.region)

        self.group_a = create_user_group(name="CZ Group A", geo_zones=[self.dept])
        self.group_b = create_user_group(name="CZ Group B")

        self.custom_zone_a = GeoCustomZone.objects.create(
            name="Zone A",
            geometry=self.dept.geometry,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        )
        self.custom_zone_a.user_groups_custom_geo_zones.add(self.group_a)

        self.custom_zone_b = GeoCustomZone.objects.create(
            name="Zone B",
            geometry=self.dept.geometry,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        )
        self.custom_zone_b.user_groups_custom_geo_zones.add(self.group_b)

        self.url = reverse("MapSettingsView")

    def test_scoped_to_group_a_sees_only_zone_a(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            self.url,
            HTTP_X_USER_GROUP_UUID=str(self.group_a.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        zone_names = [
            z["name"] for z in response.data["geo_custom_zones_uncategorized"]
        ]
        self.assertIn("Zone A", zone_names)
        self.assertNotIn("Zone B", zone_names)

    def test_scoped_to_group_b_sees_only_zone_b(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            self.url,
            HTTP_X_USER_GROUP_UUID=str(self.group_b.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        zone_names = [
            z["name"] for z in response.data["geo_custom_zones_uncategorized"]
        ]
        self.assertIn("Zone B", zone_names)
        self.assertNotIn("Zone A", zone_names)

    def test_unscoped_sees_all_zones(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        zone_names = [
            z["name"] for z in response.data["geo_custom_zones_uncategorized"]
        ]
        self.assertIn("Zone A", zone_names)
        self.assertIn("Zone B", zone_names)
