"""Tests for the `import_custom_zones` management command.

The command reads from a `detections.zae_layer` table that does not exist in the
test database, so each test provisions that table (DDL is rolled back with the
surrounding test transaction) and seeds it with rows before invoking the command.
"""

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from core.management.commands.import_custom_zones import (
    LAYER_TYPE_CATEGORY_NAME_MAP,
)
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_object,
    create_tile,
    create_tile_set,
)
from core.tests.fixtures.geo_data import (
    create_gard_department,
    create_herault_department,
    create_occitanie_region,
)

# A small valid polygon inside Hérault (department code "34"), in WGS84.
HERAULT_POLYGON_WKT = "POLYGON((3.0 43.3, 3.2 43.3, 3.2 43.5, 3.0 43.5, 3.0 43.3))"


def _create_source_table():
    with connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS detections")
        cursor.execute("DROP TABLE IF EXISTS detections.zae_layer")
        cursor.execute(
            """
            CREATE TABLE detections.zae_layer (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                layer_name varchar NULL,
                layer_type varchar NULL,
                layer_year int NULL,
                department_code varchar NULL,
                geometry geometry NULL,
                created_at date NULL
            )
            """
        )


def _insert_source_row(
    layer_type,
    department_code,
    geometry_wkt=HERAULT_POLYGON_WKT,
    layer_name=None,
    srid=4326,
):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO detections.zae_layer
                (layer_name, layer_type, layer_year, department_code, geometry)
            VALUES (%s, %s, %s, %s, ST_GeomFromText(%s, %s))
            RETURNING id
            """,
            [layer_name, layer_type, 2024, department_code, geometry_wkt, srid],
        )
        return cursor.fetchone()[0]


def _seed_categories(*layer_types):
    """Create the GeoCustomZoneCategory rows for the given layer types."""
    categories = {}
    for index, layer_type in enumerate(layer_types):
        name = LAYER_TYPE_CATEGORY_NAME_MAP[layer_type]
        categories[layer_type] = GeoCustomZoneCategory.objects.create(
            name=name,
            color=f"#{index:06x}",
            name_short=layer_type.upper(),
        )
    return categories


class ImportCustomZonesCommandTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.region = create_occitanie_region()
        self.department = create_herault_department(region=self.region)
        _create_source_table()

    def test_import_creates_zone_with_department_category_and_import_id(self):
        _seed_categories("zfee")
        source_id = _insert_source_row("zfee", "34", layer_name="ZFEE Hérault")

        call_command("import_custom_zones")

        zone = GeoCustomZone.objects.get(import_id=source_id)
        self.assertEqual(zone.name, "ZFEE Hérault")
        self.assertEqual(
            zone.geo_custom_zone_category.name,
            LAYER_TYPE_CATEGORY_NAME_MAP["zfee"],
        )
        self.assertIn(
            self.department.id,
            list(zone.geo_zones.values_list("id", flat=True)),
        )
        self.assertIsNotNone(zone.geometry)

    def test_missing_category_raises(self):
        # No category seeded at all.
        _insert_source_row("zfee", "34")
        with self.assertRaises(CommandError) as ctx:
            call_command("import_custom_zones")
        self.assertIn("Missing GeoCustomZoneCategory", str(ctx.exception))

    def test_duplicate_department_category_raises_without_force(self):
        _seed_categories("zfee")
        _insert_source_row("zfee", "34")
        call_command("import_custom_zones")
        self.assertEqual(GeoCustomZone.objects.count(), 1)

        # Insert a second source row for the same department + layer_type and re-run.
        _insert_source_row("zfee", "34")
        with self.assertRaises(CommandError) as ctx:
            call_command("import_custom_zones")
        self.assertIn("already exists", str(ctx.exception))
        # Nothing new created on the conflicting run.
        self.assertEqual(GeoCustomZone.objects.count(), 1)

    def test_duplicate_check_bypassed_with_force(self):
        _seed_categories("zfee")
        _insert_source_row("zfee", "34")
        call_command("import_custom_zones")

        # A second (distinct) source row for the same department + layer_type; the
        # first row is skipped by import_id idempotency, the second is created.
        _insert_source_row("zfee", "34")
        call_command("import_custom_zones", "--force")
        self.assertEqual(GeoCustomZone.objects.count(), 2)

    def test_reimport_is_idempotent(self):
        _seed_categories("zfee")
        _insert_source_row("zfee", "34")
        call_command("import_custom_zones")
        self.assertEqual(GeoCustomZone.objects.count(), 1)

        # Re-running with no new source rows must not create anything or raise.
        call_command("import_custom_zones")
        self.assertEqual(GeoCustomZone.objects.count(), 1)

    def test_in_batch_duplicate_raises_without_force(self):
        _seed_categories("zfee")
        # Two rows resolving to the same (department, category) in a single run.
        _insert_source_row("zfee", "34")
        _insert_source_row("zfee", "34")

        with self.assertRaises(CommandError):
            call_command("import_custom_zones")
        self.assertEqual(GeoCustomZone.objects.count(), 0)

    def test_imports_geometry_with_unset_srid(self):
        # A source geometry with no SRID (ST_SRID = 0) must not abort the import:
        # it is coerced to --source-srid (default 4326) before reprojection.
        _seed_categories("zfee")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO detections.zae_layer
                    (layer_name, layer_type, layer_year, department_code, geometry)
                VALUES (%s, %s, %s, %s, ST_GeomFromText(%s))
                RETURNING id
                """,
                ["No SRID zone", "zfee", 2024, "34", HERAULT_POLYGON_WKT],
            )
            source_id = cursor.fetchone()[0]

        call_command("import_custom_zones")

        zone = GeoCustomZone.objects.get(import_id=source_id)
        self.assertIsNotNone(zone.geometry)
        self.assertEqual(zone.geometry.srid, 4326)

    def test_unknown_department_and_layer_type_are_skipped(self):
        _seed_categories("zfee")
        # Unknown department code.
        _insert_source_row("zfee", "99")
        # Unknown layer type.
        _insert_source_row("unknown_type", "34")

        call_command("import_custom_zones")
        self.assertEqual(GeoCustomZone.objects.count(), 0)

    def test_department_codes_filter(self):
        _seed_categories("zfee", "zi")
        _insert_source_row("zfee", "34")
        # Build a second department to target with the filter exclusion.
        gard = create_gard_department(region=self.region)
        _insert_source_row("zi", gard.insee_code)

        call_command("import_custom_zones", "--department-codes", "34")

        zones = list(GeoCustomZone.objects.all())
        self.assertEqual(len(zones), 1)
        self.assertIn(
            self.department.id, list(zones[0].geo_zones.values_list("id", flat=True))
        )

    def test_ignore_categories_creates_uncategorized_zone(self):
        # No categories seeded — and we don't need any: the flag stores NULL.
        source_id = _insert_source_row("zfee", "34", layer_name="Uncat ZFEE")

        call_command("import_custom_zones", "--ignore-categories")

        zone = GeoCustomZone.objects.get(import_id=source_id)
        self.assertEqual(zone.name, "Uncat ZFEE")
        self.assertIsNone(zone.geo_custom_zone_category)
        self.assertIn(
            self.department.id,
            list(zone.geo_zones.values_list("id", flat=True)),
        )

    def test_ignore_categories_accepts_unknown_layer_type(self):
        # Unknown layer_type would normally be skipped; with --ignore-categories
        # it must produce a zone (with a NULL category and a synthesized name).
        source_id = _insert_source_row("totally_unknown", "34")

        call_command("import_custom_zones", "--ignore-categories")

        zone = GeoCustomZone.objects.get(import_id=source_id)
        self.assertIsNone(zone.geo_custom_zone_category)
        # Name falls back to "<layer_type> - <department>" when no layer_name.
        self.assertIn("totally_unknown", zone.name)
        self.assertIn(self.department.name, zone.name)

    def test_ignore_categories_skips_duplicate_pair_check(self):
        # Two rows that would normally trip the (department, category) duplicate
        # check are imported as two separate zones under --ignore-categories.
        _insert_source_row("zfee", "34", layer_name="Zone A")
        _insert_source_row("zfee", "34", layer_name="Zone B")

        call_command("import_custom_zones", "--ignore-categories")

        self.assertEqual(GeoCustomZone.objects.count(), 2)
        for zone in GeoCustomZone.objects.all():
            self.assertIsNone(zone.geo_custom_zone_category)

    def test_import_associates_detections_to_new_zones(self):
        _seed_categories("zfee")
        source_id = _insert_source_row("zfee", "34")

        # A detection whose geometry falls inside the HERAULT_POLYGON_WKT bbox
        # so the post-import association picks it up.
        tile_set = create_tile_set(name="Test TS for import")
        tile = create_tile(x=1, y=1, z=18)
        detection_object = create_detection_object()
        create_detection(
            detection_object=detection_object,
            tile=tile,
            tile_set=tile_set,
            geometry=Point(3.1, 43.4, srid=4326),
            batch_id="batch-xyz",
        )

        call_command("import_custom_zones")

        zone = GeoCustomZone.objects.get(import_id=source_id)
        # The M2M is populated by associate_detections_to_custom_zones.
        self.assertIn(
            detection_object.id,
            list(zone.detection_objects.values_list("id", flat=True)),
        )
