"""End-to-end tests for the SUPER_ADMIN `x-user-group-uuid` scope header on
endpoints that previously ignored it (commune/department/region search, parcel
list, custom-zone list, prior-letter generation, detection-data update)."""

from django.urls import reverse
from rest_framework import status

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_complete_detection_setup,
)
from core.tests.fixtures.geo_data import (
    create_herault_department,
    create_ile_de_france_region,
    create_montpellier_commune,
    create_occitanie_region,
    create_paris_commune,
    create_paris_department,
)
from core.tests.fixtures.users import (
    add_user_to_group,
    create_regular_user,
    create_super_admin,
    create_user_group,
)


class ScopeOnGeoSearchTests(BaseAPITestCase):
    """The reported leak: GET /api/geo/commune/?q=… returned every commune
    regardless of the impersonation header. Same for department + region."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-geo-sa@test.com")
        self.regular = create_regular_user(email="scope-geo-reg@test.com")

        self.occitanie = create_occitanie_region()
        self.idf = create_ile_de_france_region()
        self.herault = create_herault_department(region=self.occitanie)
        self.paris_dept = create_paris_department(region=self.idf)
        self.montpellier = create_montpellier_commune(department=self.herault)
        self.paris = create_paris_commune(department=self.paris_dept)

        self.group_herault = create_user_group(
            name="Herault group", geo_zones=[self.herault]
        )
        self.group_paris = create_user_group(
            name="Paris group", geo_zones=[self.paris_dept]
        )

    def test_commune_search_unscoped_returns_all(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get("/api/geo/commune/?q=p")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [
            c["name"]
            for c in (
                response.data.get("results", response.data)
                if isinstance(response.data, dict)
                else response.data
            )
        ]
        self.assertIn("Paris", names)
        self.assertIn("Montpellier", names)

    def test_commune_search_scoped_to_paris_group_excludes_montpellier(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            "/api/geo/commune/?q=p",
            HTTP_X_USER_GROUP_UUID=str(self.group_paris.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [
            c["name"]
            for c in (
                response.data.get("results", response.data)
                if isinstance(response.data, dict)
                else response.data
            )
        ]
        self.assertIn("Paris", names)
        self.assertNotIn("Montpellier", names)

    def test_commune_search_scoped_to_herault_group_excludes_paris(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            "/api/geo/commune/?q=p",
            HTTP_X_USER_GROUP_UUID=str(self.group_herault.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [
            c["name"]
            for c in (
                response.data.get("results", response.data)
                if isinstance(response.data, dict)
                else response.data
            )
        ]
        self.assertIn("Montpellier", names)
        self.assertNotIn("Paris", names)

    def test_department_search_scoped(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            "/api/geo/department/?q=a",
            HTTP_X_USER_GROUP_UUID=str(self.group_paris.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [
            d["name"]
            for d in (
                response.data.get("results", response.data)
                if isinstance(response.data, dict)
                else response.data
            )
        ]
        self.assertIn(self.paris_dept.name, names)
        self.assertNotIn(self.herault.name, names)

    def test_region_search_scoped(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            "/api/geo/region/?q=a",
            HTTP_X_USER_GROUP_UUID=str(self.group_paris.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [
            r["name"]
            for r in (
                response.data.get("results", response.data)
                if isinstance(response.data, dict)
                else response.data
            )
        ]
        self.assertIn("Île-de-France", names)
        self.assertNotIn("Occitanie", names)

    def test_regular_user_with_header_is_forbidden_on_commune_search(self):
        add_user_to_group(self.regular, self.group_paris)
        self.authenticate_user(self.regular)
        response = self.client.get(
            "/api/geo/commune/?q=p",
            HTTP_X_USER_GROUP_UUID=str(self.group_paris.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_uuid_on_commune_search_returns_400(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            "/api/geo/commune/?q=p",
            HTTP_X_USER_GROUP_UUID="00000000-0000-0000-0000-000000000000",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ScopeOnGeoCustomZoneListTests(BaseAPITestCase):
    """GET /api/geo/custom-zone/ must honor the impersonation header."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="scope-czlist-sa@test.com")

        self.dept = create_herault_department(region=create_occitanie_region())

        self.group_a = create_user_group(name="CZList Group A", geo_zones=[self.dept])
        self.group_b = create_user_group(name="CZList Group B")

        self.zone_a = GeoCustomZone.objects.create(
            name="CZList Zone A",
            geometry=self.dept.geometry,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        )
        self.zone_a.user_groups_custom_geo_zones.add(self.group_a)

        self.zone_b = GeoCustomZone.objects.create(
            name="CZList Zone B",
            geometry=self.dept.geometry,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        )
        self.zone_b.user_groups_custom_geo_zones.add(self.group_b)

    def test_unscoped_super_admin_sees_both_zones(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get("/api/geo/custom-zone/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [
            z["name"]
            for z in (
                response.data.get("results", response.data)
                if isinstance(response.data, dict)
                else response.data
            )
        ]
        self.assertIn("CZList Zone A", names)
        self.assertIn("CZList Zone B", names)

    def test_scoped_to_group_a_sees_only_zone_a(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            "/api/geo/custom-zone/",
            HTTP_X_USER_GROUP_UUID=str(self.group_a.uuid),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [
            z["name"]
            for z in (
                response.data.get("results", response.data)
                if isinstance(response.data, dict)
                else response.data
            )
        ]
        self.assertIn("CZList Zone A", names)
        self.assertNotIn("CZList Zone B", names)


class ScopeOnDetectionDataUpdateTests(BaseAPITestCase):
    """PATCH /api/detection-data/<uuid>/ must apply the impersonation header
    when checking edit permissions: if the SUPER_ADMIN impersonates a group
    that does not cover the detection geometry, the request must 403."""

    def setUp(self):
        super().setUp()
        from django.contrib.gis.geos import Polygon
        from core.models import GeoDepartment

        self.super_admin = create_super_admin(email="scope-dd-sa@test.com")

        setup = create_complete_detection_setup()
        self.detection = setup["detection"]
        self.detection_data = setup["detection_data"]

        # detection geometry is a Point at (3.88, 43.61). Build a department
        # whose polygon explicitly covers it so the "covering" scoping check
        # passes deterministically (the Hérault fixture polygon is slightly
        # offset and does not contain the point).
        covering_geom = Polygon(
            [
                (3.0, 43.0),
                (4.5, 43.0),
                (4.5, 44.0),
                (3.0, 44.0),
                (3.0, 43.0),
            ],
            srid=4326,
        )
        region = create_occitanie_region()
        self.dept, _ = GeoDepartment.objects.get_or_create(
            insee_code="99",
            defaults={
                "name": "DD test dept",
                "geometry": covering_geom,
                "region": region,
                "surface_km2": 100,
            },
        )

        # group that covers the dept where the detection lives
        self.group_covering = create_user_group(
            name="DD covering", geo_zones=[self.dept]
        )
        # group that covers nowhere relevant
        self.group_empty = create_user_group(name="DD empty")

    def _patch(self, headers=None):
        url = f"/api/detection-data/{self.detection_data.uuid}/"
        return self.client.patch(
            url,
            data={
                "detectionValidationStatus": DetectionValidationStatus.LEGITIMATE,
                "detectionControlStatus": DetectionControlStatus.CONTROLLED_FIELD,
            },
            format="json",
            **(headers or {}),
        )

    def test_unscoped_super_admin_can_edit(self):
        self.authenticate_user(self.super_admin)
        response = self._patch()
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_scoped_to_covering_group_can_edit(self):
        self.authenticate_user(self.super_admin)
        response = self._patch(
            {"HTTP_X_USER_GROUP_UUID": str(self.group_covering.uuid)}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_scoped_to_empty_group_cannot_edit(self):
        self.authenticate_user(self.super_admin)
        response = self._patch({"HTTP_X_USER_GROUP_UUID": str(self.group_empty.uuid)})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
