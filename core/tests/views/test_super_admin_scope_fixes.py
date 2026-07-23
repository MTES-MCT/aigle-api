"""Regression tests for the SUPER_ADMIN scope holes fixed alongside the frontend
"a scope change is a page reload" rework.

Each test here maps to a way the impersonation scope used to be dropped, letting a
scoped SUPER_ADMIN see more tile sets (years) than the group grants — or crash.
"""

from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.models.object_type_category import ObjectTypeCategory
from core.permissions.scope import UNKNOWN_SCOPED_USER_GROUP_CODE
from core.permissions.user import UserPermission
from core.services.map_settings import MapSettingsService
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
    add_user_to_group,
    create_super_admin,
    create_user_group,
)


class ScopedTileSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-fix-sa@test.com")

        self.region = create_occitanie_region()
        self.dept = create_herault_department(region=self.region)
        self.commune = create_montpellier_commune(department=self.dept)

        self.group_with_zone = create_user_group(
            name="Fix Group Zone", geo_zones=[self.dept]
        )
        self.group_without_zone = create_user_group(name="Fix Group Empty")

        self.tile_set = create_tile_set(name="Fix TS")
        self.tile_set.geo_zones.add(self.dept)

        self.map_settings_url = reverse("MapSettingsView")

    def _map_settings(self, group=None):
        kwargs = {}
        if group is not None:
            kwargs["HTTP_X_USER_GROUP_UUID"] = str(group.uuid)
        return self.client.get(self.map_settings_url, **kwargs)

    def test_scoping_to_a_group_without_geo_zones_returns_no_tile_set(self):
        """The empty collectivity filter used to make the repository skip filtering
        altogether, handing a zone-less group every tile set — i.e. every year."""
        self.authenticate_user(self.super_admin)

        response = self._map_settings(self.group_without_zone)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["tile_set_settings"], [])

    def test_scoping_to_a_group_with_geo_zones_returns_its_tile_sets(self):
        self.authenticate_user(self.super_admin)

        response = self._map_settings(self.group_with_zone)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [ts["tile_set"]["name"] for ts in response.data["tile_set_settings"]]
        self.assertIn("Fix TS", names)

    def test_unscoped_super_admin_still_sees_every_tile_set(self):
        self.authenticate_user(self.super_admin)

        response = self._map_settings()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [ts["tile_set"]["name"] for ts in response.data["tile_set_settings"]]
        self.assertIn("Fix TS", names)


class ScopedTileSetFromCoordinatesTests(BaseAPITestCase):
    """`/api/tile-set/last-from-coordinates/` backs the "add a detection" flow on the
    map. It resolved the tile set from the requester alone, ignoring the header."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-fix-coord@test.com")

        self.region = create_occitanie_region()
        self.dept = create_herault_department(region=self.region)
        self.commune = create_montpellier_commune(department=self.dept)

        self.group_with_zone = create_user_group(
            name="Coord Group Zone", geo_zones=[self.dept]
        )
        self.group_without_zone = create_user_group(name="Coord Group Empty")

        self.tile_set = create_tile_set(name="Coord TS")
        self.tile_set.geo_zones.add(self.dept)

        # Inside the Hérault fixture polygon (lng 2.9-3.7, lat 43.2-43.9).
        self.url = "/api/tile-set/last-from-coordinates/?lng=3.5&lat=43.6"

    def test_scope_is_applied(self):
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            self.url, HTTP_X_USER_GROUP_UUID=str(self.group_without_zone.uuid)
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data)

    def test_covering_group_still_resolves_the_tile_set(self):
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            self.url, HTTP_X_USER_GROUP_UUID=str(self.group_with_zone.uuid)
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data)
        self.assertEqual(response.data["name"], "Coord TS")


class ScopedUsersMeTests(BaseAPITestCase):
    """The frontend seeds its map zones and the Table commune filter from
    /users/me. Under impersonation it must describe the impersonated group, not the
    SUPER_ADMIN's own memberships."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-fix-me@test.com")

        self.region = create_occitanie_region()
        self.dept = create_herault_department(region=self.region)

        self.own_group = create_user_group(name="Me Own Group", geo_zones=[self.region])
        add_user_to_group(self.super_admin, self.own_group)

        self.scoped_group = create_user_group(
            name="Me Scoped Group", geo_zones=[self.dept]
        )

        self.url = "/api/users/me/"

    def test_unscoped_returns_own_groups(self):
        self.authenticate_user(self.super_admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [uug["user_group"]["name"] for uug in response.data["user_user_groups"]]
        self.assertEqual(names, ["Me Own Group"])

    def test_scoped_returns_only_the_impersonated_group(self):
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            self.url, HTTP_X_USER_GROUP_UUID=str(self.scoped_group.uuid)
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user_user_groups = response.data["user_user_groups"]
        self.assertEqual(len(user_user_groups), 1)
        self.assertEqual(user_user_groups[0]["user_group"]["name"], "Me Scoped Group")

        zone_names = [z["name"] for z in user_user_groups[0]["user_group"]["geo_zones"]]
        self.assertEqual(zone_names, ["Hérault"])

    def test_scoped_grants_full_rights_on_the_impersonated_group(self):
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            self.url, HTTP_X_USER_GROUP_UUID=str(self.scoped_group.uuid)
        )

        rights = response.data["user_user_groups"][0]["user_group_rights"]
        self.assertCountEqual(rights, ["WRITE", "ANNOTATE", "READ"])


class ScopedObjectTypeUuidsTests(BaseAPITestCase):
    """A stale URL carries the previous group's object-type uuids. Under
    impersonation those must not resolve — the client may narrow the selection,
    never widen it past the group's grants."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-fix-ot@test.com")

        create_object_type_category(name="Granted Cat")
        self.granted = create_object_type_with_category(
            object_type_name="Granted OT", category_name="Granted Cat"
        )
        create_object_type_category(name="Foreign Cat")
        self.foreign = create_object_type_with_category(
            object_type_name="Foreign OT", category_name="Foreign Cat"
        )

        self.group = create_user_group(name="OT Group")
        self.group.object_type_categories.add(
            ObjectTypeCategory.objects.get(name="Granted Cat")
        )

    def _resolve(self, requested, scoped_user_group=None):
        return UserPermission(
            self.super_admin, scoped_user_group=scoped_user_group
        ).resolve_object_type_uuids(requested_uuids=requested)

    def test_impersonation_drops_uuids_the_group_does_not_own(self):
        granted_uuid = _object_type_uuid("Granted OT")
        foreign_uuid = _object_type_uuid("Foreign OT")

        resolved = self._resolve(
            [str(granted_uuid), str(foreign_uuid)], scoped_user_group=self.group
        )

        self.assertEqual([str(u) for u in resolved], [str(granted_uuid)])

    def test_impersonation_with_no_request_returns_the_groups_grants(self):
        resolved = self._resolve(None, scoped_user_group=self.group)

        self.assertEqual(
            [str(u) for u in resolved], [str(_object_type_uuid("Granted OT"))]
        )

    def test_without_impersonation_the_request_is_honoured_as_is(self):
        foreign_uuid = str(_object_type_uuid("Foreign OT"))

        resolved = self._resolve([foreign_uuid])

        self.assertEqual(resolved, [foreign_uuid])


def _object_type_uuid(name: str):
    from core.models.object_type import ObjectType

    return ObjectType.objects.get(name=name).uuid


class ImpersonatedLastPositionTests(BaseAPITestCase):
    """A SUPER_ADMIN's own last_position sits wherever they last were — outside the
    impersonated group. Map settings must open on the group's centroid instead, or
    the map lands in a random corner after a group switch."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-fix-pos@test.com")
        # Paris — far outside the Hérault group below.
        self.super_admin.last_position = Point(2.3522, 48.8566, srid=4326)
        self.super_admin.save(update_fields=["last_position"])

        self.region = create_occitanie_region()
        self.dept = create_herault_department(region=self.region)
        self.group = create_user_group(name="Pos Group", geo_zones=[self.dept])

    def _build(self, scoped_user_group=None):
        return MapSettingsService(
            user=self.super_admin, scoped_user_group=scoped_user_group
        ).build_settings()

    def test_impersonation_opens_on_the_group_centroid(self):
        from core.services.user import UserService

        expected = UserService.get_user_group_centroid([self.group])

        position = self._build(scoped_user_group=self.group)["user_last_position"]

        self.assertIsNotNone(position)
        self.assertAlmostEqual(position.x, expected.x)
        self.assertAlmostEqual(position.y, expected.y)
        # Definitely not the admin's own Paris position.
        self.assertNotAlmostEqual(position.x, 2.3522)

    def test_impersonating_a_zoneless_group_falls_back_to_own_position(self):
        zoneless = create_user_group(name="Pos Zoneless")

        position = self._build(scoped_user_group=zoneless)["user_last_position"]

        self.assertAlmostEqual(position.x, 2.3522)
        self.assertAlmostEqual(position.y, 48.8566)

    def test_unscoped_keeps_the_admins_own_position(self):
        position = self._build()["user_last_position"]

        self.assertAlmostEqual(position.x, 2.3522)
        self.assertAlmostEqual(position.y, 48.8566)


class MalformedScopeHeaderTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-fix-bad@test.com")
        self.url = reverse("MapSettingsView")

    def test_malformed_uuid_returns_400_not_500(self):
        """The client persists this value in localStorage, so a 500 would brick the
        app on every request with no way back."""
        self.authenticate_user(self.super_admin)

        response = self.client.get(self.url, HTTP_X_USER_GROUP_UUID="not-a-uuid")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], UNKNOWN_SCOPED_USER_GROUP_CODE)

    def test_unknown_uuid_returns_the_recovery_code(self):
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            self.url,
            HTTP_X_USER_GROUP_UUID="00000000-0000-0000-0000-000000000000",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], UNKNOWN_SCOPED_USER_GROUP_CODE)

    def test_deleted_group_returns_the_recovery_code(self):
        group = create_user_group(name="Deleted Group")
        group.deleted = True
        group.save()

        self.authenticate_user(self.super_admin)

        response = self.client.get(self.url, HTTP_X_USER_GROUP_UUID=str(group.uuid))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], UNKNOWN_SCOPED_USER_GROUP_CODE)

    def test_empty_header_is_treated_as_no_scope(self):
        self.authenticate_user(self.super_admin)

        response = self.client.get(self.url, HTTP_X_USER_GROUP_UUID="")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
