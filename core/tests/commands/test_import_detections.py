"""Tests for the `import_detections` re-deploy safety guard.

import_detections is NOT idempotent — re-running re-inserts every inference as a
brand-new DetectionObject (the link step excludes the target tile set, and
merge_double_detections can't collapse cross-object duplicates). So the command
refuses to run when detections already exist for the batch_id, unless --force is
passed. The deploy flow never passes --force, so an accidental re-deploy is blocked.
"""

from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from core.models.detection import Detection
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import create_detection, create_tile_set

SCHEMA_SERVICE = "core.services.detections_schema.DetectionsSchemaService"
MERGE = (
    "core.services.detection_process.DetectionProcessService.merge_double_detections"
)


class ImportDetectionsGuardTests(BaseTestCase):
    def test_refuses_when_batch_already_imported(self):
        tile_set = create_tile_set(name="guard-ts")
        create_detection(batch_id="batch-already", tile_set=tile_set)

        with self.assertRaises(CommandError) as ctx:
            call_command(
                "import_detections",
                tile_set_id=tile_set.id,
                batch_id="batch-already",
            )
        self.assertIn("already imported", str(ctx.exception))
        # nothing new imported — still exactly the one pre-existing detection
        self.assertEqual(Detection.objects.filter(batch_id="batch-already").count(), 1)

    def test_force_bypasses_the_guard(self):
        tile_set = create_tile_set(name="guard-ts-force")
        create_detection(batch_id="batch-already", tile_set=tile_set)

        # the detections-schema tables don't exist in the test DB; mock the reads so the
        # command can run PAST the guard (0 inferences) — proving --force skips the check.
        with (
            patch(f"{SCHEMA_SERVICE}.get_distinct_object_types", return_value=[]),
            patch(f"{SCHEMA_SERVICE}.get_batch", return_value={"batch_name": "x"}),
            patch(f"{SCHEMA_SERVICE}.count_inferences", return_value=0),
            patch(f"{SCHEMA_SERVICE}.get_inference_rows", return_value=[]),
            patch(MERGE),
        ):
            # must NOT raise the guard's CommandError — completes with 0 new detections
            call_command(
                "import_detections",
                tile_set_id=tile_set.id,
                batch_id="batch-already",
                force=True,
            )
