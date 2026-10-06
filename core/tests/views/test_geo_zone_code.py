"""`code` on every GeoZoneSerializer payload: the collectivity's own code (commune INSEE
code, EPCI SIREN, department/region INSEE code), null for a custom zone.

The base `core_geozone` table has no code column, so the value comes either from the
`geo_zones_with_code()` annotation or from one batched lookup. The frontend derives the
Matomo "Département" dimension and the geocoder postcode filter from these codes."""

import csv
import io

from django.contrib.gis.geos import Polygon
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneStatus,
    GeoCustomZoneType,
)
from core.models.geo_zone import GeoZone
from core.tests.base import BaseAPITestCase
from core.utils.bulk_csv import BOM, COL_DEPARTMENTS, COL_EPCIS, CSV_SEP
from core.tests.fixtures.detection_data import create_tile_set
from core.tests.fixtures.geo_data import (
    create_complete_geo_hierarchy,
    create_montpellier_mediterranee_epci,
)
from core.tests.fixtures.users import (
    add_user_to_group,
    create_regular_user,
    create_super_admin,
    create_user_group,
)


class GeoZoneCodeTestsBase(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        geo = create_complete_geo_hierarchy()
        self.occitanie = geo["regions"]["occitanie"]
        self.herault = geo["departments"]["herault"]
        self.montpellier = geo["communes"]["montpellier"]
        self.beziers = geo["communes"]["beziers"]
        self.epci = create_montpellier_mediterranee_epci(
            department=self.herault, communes=[self.montpellier]
        )
        self.custom_zone = GeoCustomZone.objects.create(
            name="Zone code",
            geo_custom_zone_type=GeoCustomZoneType.COMMON,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
            color="#112233",
            geometry=Polygon(
                [(3.8, 43.5), (3.9, 43.5), (3.9, 43.6), (3.8, 43.6), (3.8, 43.5)],
                srid=4326,
            ),
        )
        self.expected_codes = {
            str(self.occitanie.uuid): "76",
            str(self.herault.uuid): "34",
            str(self.epci.uuid): "243400017",
            str(self.montpellier.uuid): "34172",
            str(self.beziers.uuid): "34032",
            str(self.custom_zone.uuid): None,
        }
        self.super_admin = create_super_admin(email="gzcode-admin@test.com")

    def assert_codes(self, zones):
        self.assertTrue(zones)
        for zone in zones:
            self.assertEqual(
                zone["code"], self.expected_codes[str(zone["uuid"])], zone["name"]
            )


class GeoZoneSerializerCodeTests(GeoZoneCodeTestsBase):
    def _serializer(self):
        import core.urls  # noqa: F401  (resolves the serializer import cycle)
        from core.serializers.geo_zone import GeoZoneSerializer

        return GeoZoneSerializer

    def test_unannotated_zones_get_their_code_in_one_query(self):
        serializer_class = self._serializer()
        zones = list(GeoZone.objects.filter(uuid__in=self.expected_codes.keys()))

        with CaptureQueriesContext(connection) as queries:
            data = serializer_class(zones, many=True).data

        self.assertEqual(len(queries), 1)
        self.assertEqual(len(data), len(self.expected_codes))
        self.assert_codes(data)

    def test_annotated_zones_cost_no_query(self):
        from core.serializers.geo_zone import geo_zones_with_code

        serializer_class = self._serializer()
        zones = list(geo_zones_with_code().filter(uuid__in=self.expected_codes.keys()))

        with CaptureQueriesContext(connection) as queries:
            data = serializer_class(zones, many=True).data

        self.assertEqual(len(queries), 0)
        self.assert_codes(data)

    def test_single_zone(self):
        serializer_class = self._serializer()
        zone = GeoZone.objects.get(id=self.montpellier.id)

        self.assertEqual(serializer_class(zone).data["code"], "34172")


class UserGroupGeoZoneCodeTests(GeoZoneCodeTestsBase):
    def setUp(self):
        super().setUp()
        self.group = create_user_group(
            name="Groupe codes",
            geo_zones=[
                self.occitanie,
                self.herault,
                self.epci,
                self.montpellier,
                self.beziers,
            ],
        )

    def test_retrieve_returns_every_level_code(self):
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            reverse("UserGroupViewSet-detail", kwargs={"uuid": str(self.group.uuid)})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assert_codes(response.data["geo_zones"])
        for level in ["regions", "departments", "epcis", "communes"]:
            self.assert_codes(response.data[level])

    def test_list_query_count_does_not_grow_with_groups(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-list")

        with CaptureQueriesContext(connection) as baseline:
            self.client.get(url)

        for index in range(3):
            create_user_group(
                name=f"Groupe codes {index}", geo_zones=[self.herault, self.beziers]
            )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(queries), len(baseline))
        for group in response.data:
            self.assert_codes(group["geo_zones"])


class UsersMeGeoZoneCodeTests(GeoZoneCodeTestsBase):
    def test_me_returns_codes(self):
        user = create_regular_user(email="gzcode-me@test.com")
        add_user_to_group(
            user,
            create_user_group(
                name="Groupe me", geo_zones=[self.herault, self.montpellier]
            ),
        )
        self.authenticate_user(user)

        response = self.client.get("/api/users/me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assert_codes(
            response.data["user_user_groups"][0]["user_group"]["geo_zones"]
        )

    def test_impersonated_group_returns_codes(self):
        scoped_group = create_user_group(
            name="Groupe impersonne", geo_zones=[self.herault, self.beziers]
        )
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            "/api/users/me/", HTTP_X_USER_GROUP_UUID=str(scoped_group.uuid)
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        zones = response.data["user_user_groups"][0]["user_group"]["geo_zones"]
        self.assertCountEqual([zone["code"] for zone in zones], ["34", "34032"])


class CollectivitiesGeoZoneCodeTests(GeoZoneCodeTestsBase):
    def test_tile_set_retrieve_returns_codes(self):
        tile_set = create_tile_set(name="TS codes")
        tile_set.geo_zones.set([self.herault, self.epci, self.montpellier])
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            reverse("TileSetViewSet-detail", kwargs={"uuid": str(tile_set.uuid)})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assert_codes(response.data["departments"])
        self.assert_codes(response.data["epcis"])
        self.assert_codes(response.data["communes"])
        self.assertEqual(response.data["regions"], [])

    def test_custom_zone_list_with_collectivities_returns_codes(self):
        self.custom_zone.geo_zones.set([self.herault, self.montpellier])
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            reverse("GeoCustomZoneViewSet-list"), {"with_collectivities": "true"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        zone = next(
            row
            for row in response.data
            if str(row["uuid"]) == str(self.custom_zone.uuid)
        )
        self.assert_codes(zone["departments"])
        self.assert_codes(zone["communes"])


class CollectivityExportCodeTests(GeoZoneCodeTestsBase):
    """The CSV exports chain a plain "geo_zones" prefetch after the annotated one."""

    def _export_rows(self, url_name):
        self.authenticate_user(self.super_admin)
        response = self.client.get(reverse(url_name))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = response.content.decode().lstrip(BOM)
        return list(csv.DictReader(io.StringIO(content), delimiter=CSV_SEP))

    def test_tile_set_export(self):
        create_tile_set(name="TS export codes").geo_zones.set([self.herault, self.epci])

        row = next(
            row
            for row in self._export_rows("TileSetViewSet-export-csv")
            if row["nom du fond de carte"] == "TS export codes"
        )

        self.assertEqual(row[COL_DEPARTMENTS], "34")
        self.assertEqual(row[COL_EPCIS], "243400017")

    def test_custom_zone_export(self):
        self.custom_zone.geo_zones.set([self.herault])

        row = next(
            row
            for row in self._export_rows("GeoCustomZoneViewSet-export-csv")
            if row["nom de la zone"] == self.custom_zone.name
        )

        self.assertEqual(row[COL_DEPARTMENTS], "34")

    def test_user_group_export(self):
        create_user_group(name="Groupe export codes", geo_zones=[self.herault])

        row = next(
            row
            for row in self._export_rows("UserGroupViewSet-export-csv")
            if row["nom du groupe"] == "Groupe export codes"
        )

        self.assertEqual(row[COL_DEPARTMENTS], "34")
