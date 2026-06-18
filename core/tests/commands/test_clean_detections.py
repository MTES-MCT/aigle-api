"""Tests for the `clean_detections` management command.

Exercises the FK-safe delete ordering: a detection's data, authorizations and the
two detection-object M2M junctions must all be removed before the rows they point
at, or Postgres rejects the purge at commit.
"""

from datetime import date

from django.core.management import call_command

from core.models.detection import Detection
from core.models.detection_authorization import DetectionAuthorization
from core.models.detection_data import DetectionData
from core.models.detection_object import DetectionObject
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.geo_sub_custom_zone import GeoSubCustomZone
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_tile,
    create_tile_set,
)


class CleanDetectionsCommandTests(BaseTestCase):
    def test_clean_by_batch_id_purges_target_and_all_dependents(self):
        tile_set = create_tile_set()
        tile = create_tile()

        # Target: a detection in batch "target" wired to every dependent that FKs it.
        data = create_detection_data()
        obj = create_detection_object()
        detection = create_detection(
            detection_object=obj,
            tile=tile,
            tile_set=tile_set,
            detection_data=data,
            batch_id="target",
        )
        DetectionAuthorization.objects.create(
            detection_data=data, authorization_date=date(2024, 1, 1)
        )
        zone = GeoCustomZone.objects.create(
            name="zone", geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE
        )
        sub_zone = GeoSubCustomZone.objects.create(name="sub", custom_zone=zone)
        obj.geo_custom_zones.add(zone)
        obj.geo_sub_custom_zones.add(sub_zone)

        # Survivor in a different batch — must be untouched.
        survivor_data = create_detection_data()
        survivor = create_detection(
            tile=tile, tile_set=tile_set, detection_data=survivor_data, batch_id="other"
        )

        call_command("clean_detections", batch_id="target")

        self.assertFalse(Detection.objects.filter(id=detection.id).exists())
        self.assertFalse(DetectionData.objects.filter(id=data.id).exists())
        self.assertFalse(
            DetectionAuthorization.objects.filter(detection_data_id=data.id).exists()
        )
        self.assertFalse(DetectionObject.objects.filter(id=obj.id).exists())

        self.assertTrue(Detection.objects.filter(id=survivor.id).exists())
        self.assertTrue(
            DetectionObject.objects.filter(id=survivor.detection_object_id).exists()
        )

    def test_clean_by_tile_set_keeps_objects_with_detections_elsewhere(self):
        tile_set_a = create_tile_set(name="A")
        tile_set_b = create_tile_set(name="B")
        tile = create_tile()

        # One object with a detection in each tile set.
        obj = create_detection_object()
        data_a = create_detection_data()
        detection_a = create_detection(
            detection_object=obj, tile=tile, tile_set=tile_set_a, detection_data=data_a
        )
        data_b = create_detection_data()
        create_detection(
            detection_object=obj, tile=tile, tile_set=tile_set_b, detection_data=data_b
        )

        call_command("clean_detections", tile_set_id=tile_set_a.id)

        # Tile set A's detection + its data are gone...
        self.assertFalse(Detection.objects.filter(id=detection_a.id).exists())
        self.assertFalse(DetectionData.objects.filter(id=data_a.id).exists())
        # ...but the object survives because it still has a detection in tile set B.
        self.assertTrue(DetectionObject.objects.filter(id=obj.id).exists())
        self.assertTrue(DetectionData.objects.filter(id=data_b.id).exists())

    def test_requires_exactly_one_selector(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("clean_detections")
