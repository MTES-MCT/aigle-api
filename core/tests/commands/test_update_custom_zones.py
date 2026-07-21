"""Tests for the `update_custom_zones` management command — removal of the links a
custom zone does not cover anymore (the association side is covered by
`test_import_custom_zones`)."""

from django.contrib.gis.geos import Point, Polygon
from django.core.management import call_command

from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_sub_custom_zone import GeoSubCustomZone
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_object,
    create_tile,
    create_tile_set,
)

ZONE_POLYGON = Polygon(
    ((3.0, 43.3), (3.2, 43.3), (3.2, 43.5), (3.0, 43.5), (3.0, 43.3)), srid=4326
)
INSIDE = Point(3.1, 43.4, srid=4326)
OUTSIDE = Point(5.0, 45.0, srid=4326)


class UpdateCustomZonesTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.zone = GeoCustomZone.objects.create(name="Zone", geometry=ZONE_POLYGON)
        self.tile = create_tile(x=1, y=1, z=18)
        self.tile_set = create_tile_set(name="TS")

    def _linked_object_ids(self, zone):
        return list(zone.detection_objects.values_list("id", flat=True))

    def test_removes_link_when_no_detection_is_covered_anymore(self):
        detection_object = create_detection_object()
        create_detection(
            detection_object=detection_object,
            tile=self.tile,
            tile_set=self.tile_set,
            geometry=OUTSIDE,
            batch_id="batch-1",
        )
        detection_object.geo_custom_zones.add(self.zone)

        call_command("update_custom_zones")

        self.assertEqual(self._linked_object_ids(self.zone), [])

    def test_keeps_link_of_covered_detection(self):
        detection_object = create_detection_object()
        create_detection(
            detection_object=detection_object,
            tile=self.tile,
            tile_set=self.tile_set,
            geometry=INSIDE,
            batch_id="batch-1",
        )
        detection_object.geo_custom_zones.add(self.zone)

        call_command("update_custom_zones")

        self.assertEqual(self._linked_object_ids(self.zone), [detection_object.id])

    def test_keeps_link_held_by_a_detection_outside_the_requested_tile_set(self):
        # Removal must not be scoped by tile set / batch: the M2M is per object, so a
        # covered detection of another tile set still holds the link.
        other_tile_set = create_tile_set(name="Other TS")
        detection_object = create_detection_object()
        create_detection(
            detection_object=detection_object,
            tile=self.tile,
            tile_set=other_tile_set,
            geometry=INSIDE,
            batch_id="batch-other",
        )
        create_detection(
            detection_object=detection_object,
            tile=self.tile,
            tile_set=self.tile_set,
            geometry=OUTSIDE,
            batch_id="batch-1",
        )
        detection_object.geo_custom_zones.add(self.zone)

        call_command("update_custom_zones", "--tile-set-uuids", str(self.tile_set.uuid))

        self.assertEqual(self._linked_object_ids(self.zone), [detection_object.id])

    def test_removes_outdated_sub_custom_zone_link(self):
        sub_zone = GeoSubCustomZone.objects.create(
            name="Sub", geometry=ZONE_POLYGON, custom_zone=self.zone
        )
        detection_object = create_detection_object()
        create_detection(
            detection_object=detection_object,
            tile=self.tile,
            tile_set=self.tile_set,
            geometry=OUTSIDE,
            batch_id="batch-1",
        )
        detection_object.geo_sub_custom_zones.add(sub_zone)

        call_command("update_custom_zones")

        self.assertEqual(self._linked_object_ids(sub_zone), [])
