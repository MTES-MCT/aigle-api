"""Tests for the `import_custom_zones` management command.

The command reads from a `detections.zae_layer` table that does not exist in the
test database, so each test provisions that table (DDL is rolled back with the
surrounding test transaction) and seeds it with rows before invoking the command.
"""

from django.contrib.gis.geos import Point, Polygon
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
    create_montpellier_commune,
    create_occitanie_region,
)
from core.tests.fixtures.users import create_user_group

# A small valid polygon inside Hérault (department code "34"), in WGS84.
HERAULT_POLYGON_WKT = "POLYGON((3.0 43.3, 3.2 43.3, 3.2 43.5, 3.0 43.5, 3.0 43.3))"
# A strict subset of it, chosen so it does NOT cover INSIDE_POINT — an override with
# this geometry must drop the detection links the wider polygon had earned.
SHRUNK_HERAULT_POLYGON_WKT = (
    "POLYGON((3.0 43.3, 3.05 43.3, 3.05 43.35, 3.0 43.35, 3.0 43.3))"
)
INSIDE_POINT = Point(3.1, 43.4, srid=4326)


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


def _update_source_geometry(source_id, geometry_wkt, srid=4326):
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE detections.zae_layer SET geometry = ST_GeomFromText(%s, %s) "
            "WHERE id = %s",
            [geometry_wkt, srid, source_id],
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

    def test_duplicate_error_mentions_override(self):
        _seed_categories("zfee")
        _insert_source_row("zfee", "34")
        call_command("import_custom_zones")
        _insert_source_row("zfee", "34")

        with self.assertRaises(CommandError) as ctx:
            call_command("import_custom_zones")
        self.assertIn("--override", str(ctx.exception))

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

        call_command("import_custom_zones", "--department-code", "34")

        zones = list(GeoCustomZone.objects.all())
        self.assertEqual(len(zones), 1)
        self.assertIn(
            self.department.id, list(zones[0].geo_zones.values_list("id", flat=True))
        )

    def test_ids_filter_restricts_to_listed_source_rows(self):
        _seed_categories("zfee", "zi")
        # Build a second department so each row's (dept, category) pair is unique.
        gard = create_gard_department(region=self.region)
        kept_id = _insert_source_row("zfee", "34", layer_name="Keep me")
        _insert_source_row("zi", gard.insee_code, layer_name="Drop me")

        call_command("import_custom_zones", "--ids", str(kept_id))

        zones = list(GeoCustomZone.objects.all())
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0].import_id, kept_id)
        self.assertEqual(zones[0].name, "Keep me")

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

    def test_import_associates_user_groups_by_department_and_commune(self):
        _seed_categories("zfee")
        montpellier = create_montpellier_commune(department=self.department)
        # A DDTM group scoped to the department, and a collectivity group scoped to
        # a commune of that department — both must get the new zone.
        ddtm_group = create_user_group(name="DDTM 34", geo_zones=[self.department])
        commune_group = create_user_group(name="Montpellier", geo_zones=[montpellier])
        # A group scoped to an unrelated department must NOT get the zone.
        gard = create_gard_department(region=self.region)
        other_group = create_user_group(name="DDTM 30", geo_zones=[gard])

        source_id = _insert_source_row("zfee", "34")
        call_command("import_custom_zones")
        zone = GeoCustomZone.objects.get(import_id=source_id)

        self.assertIn(zone, ddtm_group.geo_custom_zones.all())
        self.assertIn(zone, commune_group.geo_custom_zones.all())
        self.assertNotIn(zone, other_group.geo_custom_zones.all())

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

    def test_import_does_not_associate_detection_straddling_zone_boundary(self):
        # The zone is HERAULT_POLYGON_WKT ((3.0,43.3)-(3.2,43.5)). A detection that
        # crosses the x=3.2 edge is only partially inside — ST_Covers is false, so it
        # must NOT be associated. Locks the fully-inside rule on the bulk recompute
        # (a plain intersects would wrongly associate it).
        _seed_categories("zfee")
        source_id = _insert_source_row("zfee", "34")

        tile_set = create_tile_set(name="Straddle TS")
        tile = create_tile(x=2, y=2, z=18)
        detection_object = create_detection_object()
        create_detection(
            detection_object=detection_object,
            tile=tile,
            tile_set=tile_set,
            geometry=Polygon(
                (
                    (3.15, 43.35),
                    (3.25, 43.35),
                    (3.25, 43.45),
                    (3.15, 43.45),
                    (3.15, 43.35),
                ),
                srid=4326,
            ),
            batch_id="batch-straddle",
        )

        call_command("import_custom_zones")

        zone = GeoCustomZone.objects.get(import_id=source_id)
        self.assertNotIn(
            detection_object.id,
            list(zone.detection_objects.values_list("id", flat=True)),
        )


class ImportCustomZonesOverrideTests(BaseTestCase):
    """`--override`: replace the custom zone a source row conflicts with instead of
    aborting on the (department, category) duplicate check, then refresh its detection
    links exactly as `update_custom_zones` does."""

    def setUp(self):
        super().setUp()
        self.region = create_occitanie_region()
        self.department = create_herault_department(region=self.region)
        _create_source_table()
        # "zi" is seeded up front (its colour must stay unique) so a test can move a
        # source row to another layer_type without reseeding.
        self.categories = _seed_categories("zfee", "zi")

    def _import_first_zone(self, layer_name="ZFEE Hérault"):
        source_id = _insert_source_row("zfee", "34", layer_name=layer_name)
        call_command("import_custom_zones")
        return source_id, GeoCustomZone.objects.get(import_id=source_id)

    def _covered_object_ids(self, zone):
        return list(zone.detection_objects.values_list("id", flat=True))

    def _create_covered_detection(self, geometry=INSIDE_POINT, batch_id="batch-ovr"):
        detection_object = create_detection_object()
        create_detection(
            detection_object=detection_object,
            tile=create_tile(x=1, y=1, z=18),
            tile_set=create_tile_set(name="Override TS"),
            geometry=geometry,
            batch_id=batch_id,
        )
        return detection_object

    def test_override_replaces_the_zone_holding_the_pair(self):
        # A DIFFERENT source row for the same (department, category): without --override
        # this is the CommandError the admin interface reports.
        _, zone = self._import_first_zone()
        new_source_id = _insert_source_row(
            "zfee", "34", geometry_wkt=SHRUNK_HERAULT_POLYGON_WKT, layer_name="ZFEE v2"
        )

        call_command("import_custom_zones", "--override")

        # replaced, not duplicated — and the very same row, so anything pointing at its
        # uuid (user groups, detection links, saved app state) still resolves
        self.assertEqual(GeoCustomZone.objects.count(), 1)
        zone.refresh_from_db()
        self.assertEqual(zone.import_id, new_source_id)
        self.assertEqual(zone.import_layer_name, "ZFEE v2")
        self.assertEqual(zone.name, "ZFEE v2")
        self.assertEqual(zone.name_normalized, "zfee v2")
        self.assertEqual(zone.geo_custom_zone_category, self.categories["zfee"])
        self.assertEqual(
            list(zone.geo_zones.values_list("id", flat=True)), [self.department.id]
        )

    def test_override_writes_the_new_geometry(self):
        _, zone = self._import_first_zone()
        original_uuid = zone.uuid
        _insert_source_row(
            "zfee", "34", geometry_wkt=SHRUNK_HERAULT_POLYGON_WKT, layer_name="ZFEE v2"
        )

        call_command("import_custom_zones", "--override")

        zone.refresh_from_db()
        self.assertEqual(zone.uuid, original_uuid)
        # the shrunk polygon no longer covers the point the original one did
        self.assertFalse(zone.geometry.covers(INSIDE_POINT))
        self.assertEqual(zone.geometry.srid, 4326)

    def test_override_reimports_the_same_source_row(self):
        # Without --override an already-imported row is skipped by import_id; with it,
        # the row is re-read so an edited source geometry actually reaches the zone.
        source_id, zone = self._import_first_zone()
        _update_source_geometry(source_id, SHRUNK_HERAULT_POLYGON_WKT)

        call_command("import_custom_zones", "--override")

        self.assertEqual(GeoCustomZone.objects.count(), 1)
        zone.refresh_from_db()
        self.assertEqual(zone.import_id, source_id)
        self.assertFalse(zone.geometry.covers(INSIDE_POINT))

    def test_override_removes_detection_links_the_new_geometry_misses(self):
        # This is the update_custom_zones refresh: the plain import only ever ADDS links,
        # so without it the object would stay attached to a zone that no longer covers it.
        detection_object = self._create_covered_detection()
        source_id, zone = self._import_first_zone()
        self.assertEqual(self._covered_object_ids(zone), [detection_object.id])

        _update_source_geometry(source_id, SHRUNK_HERAULT_POLYGON_WKT)
        call_command("import_custom_zones", "--override")

        zone.refresh_from_db()
        self.assertEqual(self._covered_object_ids(zone), [])

    def test_override_adds_detection_links_the_new_geometry_gains(self):
        source_id, zone = self._import_first_zone()
        _update_source_geometry(source_id, SHRUNK_HERAULT_POLYGON_WKT)
        call_command("import_custom_zones", "--override")

        # a detection covered only by the ORIGINAL polygon, added after the shrink
        detection_object = self._create_covered_detection()
        _update_source_geometry(source_id, HERAULT_POLYGON_WKT)
        call_command("import_custom_zones", "--override")

        zone.refresh_from_db()
        self.assertEqual(self._covered_object_ids(zone), [detection_object.id])

    def test_override_keeps_a_name_edited_in_the_app(self):
        # `name` is admin-editable; `import_layer_name` records what the import set it to.
        # Once they differ somebody renamed the zone, and a re-import must not undo it.
        _, zone = self._import_first_zone()
        zone.name = "Nom choisi par l'admin"
        zone.save()
        _insert_source_row("zfee", "34", layer_name="ZFEE v2")

        call_command("import_custom_zones", "--override")

        zone.refresh_from_db()
        self.assertEqual(zone.name, "Nom choisi par l'admin")
        # the source tracking still moves to the new row
        self.assertEqual(zone.import_layer_name, "ZFEE v2")

    def test_override_refreshes_a_generated_name_when_the_category_changed(self):
        # A source row with no layer_name is named from its category, and stores
        # import_layer_name = NULL. That NULL must not be read as "renamed in the app":
        # the zone would keep naming the category it no longer belongs to.
        source_id = _insert_source_row("zfee", "34", layer_name=None)
        call_command("import_custom_zones")
        zone = GeoCustomZone.objects.get(import_id=source_id)
        self.assertEqual(
            zone.name,
            f"{LAYER_TYPE_CATEGORY_NAME_MAP['zfee']} - {self.department.name}",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE detections.zae_layer SET layer_type = 'zi' WHERE id = %s",
                [source_id],
            )
        call_command("import_custom_zones", "--override")

        zone.refresh_from_db()
        self.assertEqual(
            zone.name, f"{LAYER_TYPE_CATEGORY_NAME_MAP['zi']} - {self.department.name}"
        )
        self.assertEqual(zone.geo_custom_zone_category, self.categories["zi"])

    def test_override_picks_up_a_layer_name_the_source_row_gained(self):
        source_id = _insert_source_row("zfee", "34", layer_name=None)
        call_command("import_custom_zones")

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE detections.zae_layer SET layer_name = %s WHERE id = %s",
                ["ZFEE nommée", source_id],
            )
        call_command("import_custom_zones", "--override")

        zone = GeoCustomZone.objects.get(import_id=source_id)
        self.assertEqual(zone.name, "ZFEE nommée")
        self.assertEqual(zone.import_layer_name, "ZFEE nommée")

    def test_override_keeps_a_renamed_zone_that_had_no_source_layer_name(self):
        # The protection still holds for a generated name: renaming it in the app makes
        # it differ from what the import wrote, so the import leaves it alone.
        source_id = _insert_source_row("zfee", "34", layer_name=None)
        call_command("import_custom_zones")
        zone = GeoCustomZone.objects.get(import_id=source_id)
        zone.name = "Nom choisi par l'admin"
        zone.save()

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE detections.zae_layer SET layer_name = %s WHERE id = %s",
                ["ZFEE nommée", source_id],
            )
        call_command("import_custom_zones", "--override")

        zone.refresh_from_db()
        self.assertEqual(zone.name, "Nom choisi par l'admin")
        self.assertEqual(zone.import_layer_name, "ZFEE nommée")

    def test_override_never_replaces_a_zone_drawn_in_the_app(self):
        # A zone with no import_id was drawn by hand: overwriting its geometry would
        # destroy user work, so the row is created alongside it instead.
        hand_drawn = GeoCustomZone.objects.create(
            name="Zone dessinée à la main",
            geometry=Polygon(
                ((3.0, 43.3), (3.2, 43.3), (3.2, 43.5), (3.0, 43.5), (3.0, 43.3)),
                srid=4326,
            ),
            geo_custom_zone_category=self.categories["zfee"],
        )
        hand_drawn.geo_zones.add(self.department)
        source_id = _insert_source_row("zfee", "34", layer_name="ZFEE Hérault")

        call_command("import_custom_zones", "--override")

        self.assertEqual(GeoCustomZone.objects.count(), 2)
        hand_drawn.refresh_from_db()
        self.assertEqual(hand_drawn.name, "Zone dessinée à la main")
        self.assertIsNone(hand_drawn.import_id)
        self.assertTrue(GeoCustomZone.objects.filter(import_id=source_id).exists())

    def test_override_associates_user_groups_added_since_the_first_import(self):
        _, zone = self._import_first_zone()
        montpellier = create_montpellier_commune(department=self.department)
        late_group = create_user_group(name="Montpellier", geo_zones=[montpellier])
        self.assertNotIn(zone, late_group.geo_custom_zones.all())

        _insert_source_row("zfee", "34", layer_name="ZFEE v2")
        call_command("import_custom_zones", "--override")

        self.assertIn(zone, late_group.geo_custom_zones.all())

    def test_override_keeps_only_the_latest_of_two_rows_claiming_one_pair(self):
        # Two source rows claiming one (department, category) is the case that aborts
        # without a flag. Overriding resolves it the only way it can — one zone — and
        # rows are written in source-id order, so the outcome is the same on every run.
        first_source_id = _insert_source_row("zfee", "34", layer_name="A")
        last_source_id = _insert_source_row("zfee", "34", layer_name="B")

        call_command("import_custom_zones", "--override")

        zone = GeoCustomZone.objects.get()
        self.assertEqual(zone.import_id, last_source_id)
        self.assertEqual(zone.name, "B")
        self.assertFalse(
            GeoCustomZone.objects.filter(import_id=first_source_id).exists()
        )

    def test_override_refreshes_each_zone_that_owns_its_own_source_row(self):
        # Regression: rows must be matched to a zone one by one. Two rows that END UP
        # on the same (department, category) — here because one had its layer_type
        # corrected — still own distinct zones through import_id, and dropping either
        # would leave a zone stale with the very flag meant to refresh it.
        zfee_source_id, zfee_zone = self._import_first_zone()
        zi_source_id = _insert_source_row("zi", "34", layer_name="ZI Hérault")
        call_command("import_custom_zones")
        zi_zone = GeoCustomZone.objects.get(import_id=zi_source_id)

        # the zfee row is retyped at source: both rows now claim (Hérault, ZI)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE detections.zae_layer SET layer_type = 'zi' WHERE id = %s",
                [zfee_source_id],
            )
        _update_source_geometry(zfee_source_id, SHRUNK_HERAULT_POLYGON_WKT)
        _update_source_geometry(zi_source_id, SHRUNK_HERAULT_POLYGON_WKT)

        call_command("import_custom_zones", "--override")

        # both zones survive and both were refreshed — neither row was dropped
        self.assertEqual(GeoCustomZone.objects.count(), 2)
        for zone in (zfee_zone, zi_zone):
            zone.refresh_from_db()
            self.assertFalse(zone.geometry.covers(INSIDE_POINT), zone.name)
        zfee_zone.refresh_from_db()
        self.assertEqual(
            zfee_zone.geo_custom_zone_category.name, LAYER_TYPE_CATEGORY_NAME_MAP["zi"]
        )

    def test_override_updates_the_category_when_the_layer_type_changed(self):
        # A layer_type corrected at source must move the zone to the right category,
        # otherwise it keeps occupying the pair it no longer belongs to.
        source_id, zone = self._import_first_zone()
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE detections.zae_layer SET layer_type = 'zi' WHERE id = %s",
                [source_id],
            )

        call_command("import_custom_zones", "--override")

        zone.refresh_from_db()
        self.assertEqual(
            zone.geo_custom_zone_category.name, LAYER_TYPE_CATEGORY_NAME_MAP["zi"]
        )

    def test_override_with_ignore_categories_keeps_an_existing_category(self):
        # --ignore-categories resolves every row to a NULL category; that must not wipe
        # the category a previous categorized import set on the zone.
        source_id, zone = self._import_first_zone()

        call_command("import_custom_zones", "--override", "--ignore-categories")

        zone.refresh_from_db()
        self.assertEqual(zone.import_id, source_id)
        self.assertEqual(
            zone.geo_custom_zone_category.name, LAYER_TYPE_CATEGORY_NAME_MAP["zfee"]
        )

    def test_override_wins_over_force(self):
        # --force creates duplicates, --override replaces; together the replacement
        # wins, so a run can never both replace and duplicate the same zone.
        _insert_source_row("zfee", "34", layer_name="A")
        _insert_source_row("zfee", "34", layer_name="B")

        call_command("import_custom_zones", "--override", "--force")

        self.assertEqual(GeoCustomZone.objects.count(), 1)

    def test_override_creates_normally_when_nothing_conflicts(self):
        source_id = _insert_source_row("zfee", "34", layer_name="ZFEE Hérault")

        call_command("import_custom_zones", "--override")

        zone = GeoCustomZone.objects.get(import_id=source_id)
        self.assertEqual(zone.name, "ZFEE Hérault")
        self.assertIn(
            self.department.id, list(zone.geo_zones.values_list("id", flat=True))
        )

    def test_override_with_ignore_categories_matches_only_the_source_row(self):
        # Uncategorized zones share the (department, NULL) pair, so it is not a usable
        # key: only the row's own import_id can identify the zone to replace.
        source_id = _insert_source_row("zfee", "34", layer_name="Uncat")
        call_command("import_custom_zones", "--ignore-categories")
        _update_source_geometry(source_id, SHRUNK_HERAULT_POLYGON_WKT)
        _insert_source_row("zfee", "34", layer_name="Autre zone non catégorisée")

        call_command("import_custom_zones", "--override", "--ignore-categories")

        # the first row refreshed its own zone, the second created a new one
        self.assertEqual(GeoCustomZone.objects.count(), 2)
        zone = GeoCustomZone.objects.get(import_id=source_id)
        self.assertIsNone(zone.geo_custom_zone_category)
        self.assertFalse(zone.geometry.covers(INSIDE_POINT))

    def test_override_ignores_a_soft_deleted_zone(self):
        # A soft-deleted zone is invisible to the import (as it is to the deploy status),
        # so the row is imported fresh rather than resurrecting it.
        _, zone = self._import_first_zone()
        zone.deleted = True
        zone.save()
        new_source_id = _insert_source_row("zfee", "34", layer_name="ZFEE v2")

        call_command("import_custom_zones", "--override")

        created = GeoCustomZone.objects.get(import_id=new_source_id)
        self.assertNotEqual(created.id, zone.id)
        zone.refresh_from_db()
        self.assertTrue(zone.deleted)
