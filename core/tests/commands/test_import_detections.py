"""Tests for `import_detections` re-deploy safety.

Re-deploying a batch replays every source row, so the command skips the rows it already
imported for that batch_id and UniqueConstraint(batch_id, import_id) backstops it at the
DB level. It also owns the tile set's reveal: the deploy creates tile sets DEACTIVATED
and passes --activate-tile-set so they only turn VISIBLE once the import completes.
"""

from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction

from core.management.commands.import_detections import slippy_tile_xy
from core.models.detection import Detection
from core.models.tile import TILE_DEFAULT_ZOOM
from core.models.tile_set import TileSet, TileSetStatus
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_object_type,
    create_tile,
    create_tile_set,
)

SCHEMA_SERVICE = "core.services.detections_schema.DetectionsSchemaService"
MERGE = (
    "core.services.detection_process.DetectionProcessService.merge_double_detections"
)
REFRESH_CACHE = "core.services.deployed_data.DeployedDataService.refresh_cache"

# distinct from create_detection_object's default type, so a pre-existing detection at
# the same spot is never linked to the imported one
OBJECT_TYPE_NAME = "Swimming Pool"
GEOMETRY = (
    "POLYGON ((3.88 43.61, 3.8801 43.61, 3.8801 43.6101, 3.88 43.6101, 3.88 43.61))"
)
CENTROID_LON, CENTROID_LAT = 3.88005, 43.61005


def _inference_row(import_id):
    return {
        "id": import_id,
        "score": 0.9,
        "address": None,
        "object_type": OBJECT_TYPE_NAME.lower(),
        "geometry": GEOMETRY,
    }


def _run(tile_set, batch_id, rows, **kwargs):
    """Run the command with the detections schema (absent from the test DB) mocked out."""
    with (
        patch(f"{SCHEMA_SERVICE}.get_distinct_object_types", return_value=[]),
        patch(f"{SCHEMA_SERVICE}.get_batch", return_value={"batch_name": "x"}),
        patch(f"{SCHEMA_SERVICE}.count_inferences", return_value=len(rows)),
        patch(f"{SCHEMA_SERVICE}.get_inference_rows", return_value=rows),
        patch(MERGE),
        patch(REFRESH_CACHE),
    ):
        call_command(
            "import_detections",
            tile_set_id=tile_set.id,
            batch_id=batch_id,
            **kwargs,
        )


class ImportDetectionsIdempotencyTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        create_object_type(name=OBJECT_TYPE_NAME)
        # the detection lands on this tile; without it every row is silently dropped
        tile_x, tile_y = slippy_tile_xy(CENTROID_LON, CENTROID_LAT, TILE_DEFAULT_ZOOM)
        create_tile(x=tile_x, y=tile_y, z=TILE_DEFAULT_ZOOM)

    def test_imports_a_new_inference_row(self):
        """Positive control: without it the skip test below would prove nothing."""
        tile_set = create_tile_set(name="ts-new")

        _run(tile_set, "batch-new", [_inference_row(42)])

        self.assertEqual(Detection.objects.get(batch_id="batch-new").import_id, 42)

    def test_skips_rows_already_imported_for_the_batch(self):
        tile_set = create_tile_set(name="ts-skip")
        create_detection(batch_id="batch-done", tile_set=tile_set, import_id=42)

        _run(tile_set, "batch-done", [_inference_row(42)])

        self.assertEqual(Detection.objects.filter(batch_id="batch-done").count(), 1)

    def test_imports_only_the_rows_not_yet_imported(self):
        tile_set = create_tile_set(name="ts-partial")
        create_detection(batch_id="batch-partial", tile_set=tile_set, import_id=42)

        _run(tile_set, "batch-partial", [_inference_row(42), _inference_row(43)])

        self.assertEqual(
            sorted(
                Detection.objects.filter(batch_id="batch-partial").values_list(
                    "import_id", flat=True
                )
            ),
            [42, 43],
        )

    def test_duplicate_batch_and_import_id_is_rejected_by_the_database(self):
        tile_set = create_tile_set(name="ts-constraint")
        create_detection(batch_id="batch-uniq", tile_set=tile_set, import_id=1)

        with self.assertRaises(IntegrityError), transaction.atomic():
            create_detection(batch_id="batch-uniq", tile_set=tile_set, import_id=1)

    def test_same_import_id_in_another_batch_is_allowed(self):
        """import_id is only unique within a batch: batches copied from another
        environment reuse that environment's core_detection ids, which do collide."""
        tile_set = create_tile_set(name="ts-other-batch")
        create_detection(batch_id="batch-a", tile_set=tile_set, import_id=1)
        create_detection(batch_id="batch-b", tile_set=tile_set, import_id=1)

        self.assertEqual(Detection.objects.filter(import_id=1).count(), 2)


class ImportDetectionsActivationTests(BaseTestCase):
    def test_activate_tile_set_makes_it_visible_when_the_import_completes(self):
        tile_set = create_tile_set(
            name="ts-activate", tile_set_status=TileSetStatus.DEACTIVATED
        )

        _run(tile_set, "batch-activate", [], activate_tile_set=True)

        self.assertEqual(
            TileSet.objects.get(id=tile_set.id).tile_set_status, TileSetStatus.VISIBLE
        )

    def test_status_is_untouched_without_the_flag(self):
        """A deploy onto a REUSED tile set never passes the flag: the tile set may
        already have users, so its status must not change."""
        tile_set = create_tile_set(
            name="ts-no-activate", tile_set_status=TileSetStatus.HIDDEN
        )

        _run(tile_set, "batch-no-activate", [])

        self.assertEqual(
            TileSet.objects.get(id=tile_set.id).tile_set_status, TileSetStatus.HIDDEN
        )
