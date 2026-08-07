"""import_geoepcis: membership is an authorization boundary, so the command must be
re-runnable and its stored geometry must agree with the FK membership it writes."""

from django.contrib.gis.geos import Polygon
from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from core.models.geo_commune import GeoCommune
from core.models.geo_epci import GeoEpci
from core.tests.fixtures.geo_data import (
    create_beziers_commune,
    create_gard_department,
    create_herault_department,
    create_montpellier_commune,
    create_nimes_commune,
)

SOURCE_SCHEMA = "epci"
SOURCE_TABLE = "epci"


def _provision_source():
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {SOURCE_SCHEMA}")
        cursor.execute(f"DROP TABLE IF EXISTS {SOURCE_SCHEMA}.{SOURCE_TABLE}")
        cursor.execute(
            f"""
            CREATE TABLE {SOURCE_SCHEMA}.{SOURCE_TABLE} (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                code_siren varchar NULL,
                nom varchar NULL,
                geometry geometry(Geometry, 4326) NULL
            )
            """
        )


def _insert_source(code_siren, nom, geometry):
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {SOURCE_SCHEMA}.{SOURCE_TABLE} (code_siren, nom, geometry) "
            "VALUES (%s, %s, ST_GeomFromText(%s, 4326))",
            [code_siren, nom, geometry.wkt],
        )


def _bbox(min_lon, min_lat, max_lon, max_lat):
    return Polygon(
        [
            (min_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, max_lat),
            (min_lon, max_lat),
            (min_lon, min_lat),
        ],
        srid=4326,
    )


class ImportGeoEpcisTests(TestCase):
    def setUp(self):
        self.herault = create_herault_department()
        self.gard = create_gard_department()
        self.montpellier = create_montpellier_commune(department=self.herault)
        self.beziers = create_beziers_commune(department=self.herault)
        self.nimes = create_nimes_commune(department=self.gard)
        _provision_source()

    def test_stored_geometry_covers_its_member_communes(self):
        """Membership is decided on a 60% areal overlap, so the SOURCE polygon can clip
        a member commune. The stored geometry must be the union of the members instead —
        a group scoped to an EPCI derives its accessible geometry from it, and a polygon
        narrower than its members would hide part of them from the map."""
        # Covers ~75% of Montpellier (3.83-3.93) and none of the others.
        clipping_source = _bbox(3.80, 43.50, 3.905, 43.70)
        self.assertFalse(clipping_source.covers(self.montpellier.geometry))

        _insert_source("200000001", "EPCI test", clipping_source)
        call_command("import_geoepcis")

        epci = GeoEpci.objects.get(siren_code="200000001")
        self.montpellier.refresh_from_db()

        self.assertEqual(self.montpellier.epci_id, epci.id)
        self.assertTrue(
            epci.geometry.covers(self.montpellier.geometry),
            "stored EPCI geometry does not cover its own member commune",
        )

    def test_is_idempotent_and_refreshes_membership(self):
        _insert_source("200000002", "EPCI initial", _bbox(3.70, 43.45, 3.99, 43.72))
        call_command("import_geoepcis")

        epci = GeoEpci.objects.get(siren_code="200000002")
        self.montpellier.refresh_from_db()
        self.assertEqual(self.montpellier.epci_id, epci.id)

        # Re-run with a polygon that drops Montpellier and takes Béziers instead.
        _provision_source()
        _insert_source("200000002", "EPCI renommée", _bbox(3.14, 43.26, 3.30, 43.42))
        call_command("import_geoepcis")

        self.assertEqual(GeoEpci.objects.filter(siren_code="200000002").count(), 1)
        epci.refresh_from_db()
        self.montpellier.refresh_from_db()
        self.beziers.refresh_from_db()

        self.assertEqual(epci.name, "EPCI renommée")
        # A stale link would keep granting access through the EPCI.
        self.assertIsNone(self.montpellier.epci_id)
        self.assertEqual(self.beziers.epci_id, epci.id)

    def test_department_code_restricts_the_import(self):
        _insert_source("200000003", "EPCI Hérault", _bbox(3.70, 43.45, 3.99, 43.72))
        _insert_source("200000004", "EPCI Gard", _bbox(4.30, 43.78, 4.42, 43.90))

        call_command("import_geoepcis", "--department-code", "34")

        self.assertTrue(GeoEpci.objects.filter(siren_code="200000003").exists())
        self.assertFalse(GeoEpci.objects.filter(siren_code="200000004").exists())

    def test_a_zero_area_commune_does_not_abort_the_import(self):
        GeoCommune.objects.create(
            iso_code="34999",
            name="Dégénérée",
            department=self.herault,
            geometry=Polygon(
                [(3.85, 43.60), (3.85, 43.60), (3.85, 43.60), (3.85, 43.60)],
                srid=4326,
            ),
        )
        _insert_source("200000005", "EPCI test", _bbox(3.70, 43.45, 3.99, 43.72))

        call_command("import_geoepcis")

        self.assertTrue(GeoEpci.objects.filter(siren_code="200000005").exists())
