"""Tests for the `update_detectionobject_commune` management command.

Pins the semantics of the set-based UPDATE: the commune comes from the centroid of
the object's *first* detection (lowest id), objects that already have a commune are
skipped unless --force is passed, and objects with no detection (or a detection
outside every commune) are left untouched.
"""

from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.management import call_command

from core.models.detection_object import DetectionObject
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_object,
    create_tile,
    create_tile_set,
)
from core.tests.fixtures.geo_data import (
    create_beziers_commune,
    create_herault_department,
    create_montpellier_commune,
)

MONTPELLIER_POINT = Point(3.88, 43.61, srid=4326)
BEZIERS_POINT = Point(3.22, 43.34, srid=4326)
# Well outside every commune fixture's polygon.
NOWHERE_POINT = Point(1.0, 47.0, srid=4326)


class UpdateDetectionObjectCommuneCommandTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        department = create_herault_department()
        self.montpellier = create_montpellier_commune(department=department)
        self.beziers = create_beziers_commune(department=department)
        self.tile_set = create_tile_set()
        self.tile = create_tile()

    def _create_object(self, geometry, commune=None, **kwargs):
        obj = create_detection_object(commune=commune)
        create_detection(
            detection_object=obj,
            tile=self.tile,
            tile_set=self.tile_set,
            geometry=geometry,
            **kwargs,
        )
        return obj

    def _commune_of(self, obj):
        return DetectionObject.objects.get(id=obj.id).commune

    def test_sets_commune_from_detection_centroid(self):
        obj = self._create_object(MONTPELLIER_POINT)

        call_command("update_detectionobject_commune")

        self.assertEqual(self._commune_of(obj), self.montpellier)

    def test_uses_first_detection_when_object_has_several(self):
        obj = create_detection_object()
        # Lowest id wins, matching the previous `detections.first()` behaviour.
        create_detection(
            detection_object=obj,
            tile=self.tile,
            tile_set=self.tile_set,
            geometry=BEZIERS_POINT,
        )
        create_detection(
            detection_object=obj,
            tile=self.tile,
            tile_set=self.tile_set,
            geometry=MONTPELLIER_POINT,
        )

        call_command("update_detectionobject_commune")

        self.assertEqual(self._commune_of(obj), self.beziers)

    def test_skips_objects_that_already_have_a_commune(self):
        # Deliberately wrong commune: without --force it must survive untouched.
        obj = self._create_object(MONTPELLIER_POINT, commune=self.beziers)

        call_command("update_detectionobject_commune")

        self.assertEqual(self._commune_of(obj), self.beziers)

    def test_force_rewrites_an_already_set_commune(self):
        obj = self._create_object(MONTPELLIER_POINT, commune=self.beziers)

        call_command("update_detectionobject_commune", "--force")

        self.assertEqual(self._commune_of(obj), self.montpellier)

    def test_object_without_detection_is_left_alone(self):
        obj = create_detection_object()

        call_command("update_detectionobject_commune")

        self.assertIsNone(self._commune_of(obj))

    def test_detection_outside_every_commune_is_left_alone(self):
        obj = self._create_object(NOWHERE_POINT)

        call_command("update_detectionobject_commune")

        self.assertIsNone(self._commune_of(obj))

    def test_batching_covers_every_object(self):
        objects = [self._create_object(MONTPELLIER_POINT) for _ in range(5)]

        call_command("update_detectionobject_commune", "--batch-size", "2")

        for obj in objects:
            self.assertEqual(self._commune_of(obj), self.montpellier)

    def test_refreshes_deployed_data_cache_when_rows_changed(self):
        self._create_object(MONTPELLIER_POINT)

        with patch(
            "core.management.commands.update_detectionobject_commune.DeployedDataService.refresh_cache"
        ) as refresh_cache:
            call_command("update_detectionobject_commune")

        refresh_cache.assert_called_once()

    def test_skips_deployed_data_refresh_when_nothing_changed(self):
        # Nothing to update: the full-dataset recompute must not run for free.
        self._create_object(NOWHERE_POINT)

        with patch(
            "core.management.commands.update_detectionobject_commune.DeployedDataService.refresh_cache"
        ) as refresh_cache:
            call_command("update_detectionobject_commune")

        refresh_cache.assert_not_called()

    def test_tile_set_uuids_scopes_the_update(self):
        other_tile_set = create_tile_set(name="Other TileSet")
        target = self._create_object(MONTPELLIER_POINT)
        untouched = create_detection_object()
        create_detection(
            detection_object=untouched,
            tile=self.tile,
            tile_set=other_tile_set,
            geometry=MONTPELLIER_POINT,
        )

        call_command(
            "update_detectionobject_commune",
            "--tile-set-uuids",
            str(self.tile_set.uuid),
        )

        self.assertEqual(self._commune_of(target), self.montpellier)
        self.assertIsNone(self._commune_of(untouched))
