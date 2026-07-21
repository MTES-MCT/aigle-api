from django.contrib.gis.geos import Polygon

from core.models.geo_commune import GeoCommune
from core.models.geo_custom_zone import GeoCustomZone
from core.services.detection import DetectionService
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_object_type,
    create_tile,
    create_tile_set,
)
from core.tests.fixtures.geo_data import create_montpellier_commune
from core.tests.fixtures.users import create_super_admin

COVERAGE_ERROR = "outside the tile set coverage"


def far_geometry():
    # ~9500 km from Montpellier (La Réunion) — cannot intersect the tile set coverage
    return Polygon(
        [
            (55.5000, -20.9000),
            (55.5010, -20.9000),
            (55.5010, -20.8990),
            (55.5000, -20.8990),
            (55.5000, -20.9000),
        ],
        srid=4326,
    )


def montpellier_geometry():
    return Polygon(
        [
            (3.8799, 43.6099),
            (3.8801, 43.6099),
            (3.8801, 43.6101),
            (3.8799, 43.6101),
            (3.8799, 43.6099),
        ],
        srid=4326,
    )


class CreateDetectionCoverageGuardTestCase(BaseAPITestCase):
    """create_detection must refuse a geometry outside the tile set's coverage.

    Regression guard for the cross-region junk incident: reusing a detection_object
    across every tile set (the "force visible on all backgrounds" flow) attached a real
    geometry to tile sets thousands of km away.
    """

    def setUp(self):
        super().setUp()
        self.user = create_super_admin()  # unrestricted -> passes the edit permission
        self.commune = create_montpellier_commune()
        self.object_type = create_object_type()
        self.tile_set = create_tile_set(name="Montpellier 2024")
        self.tile_set.geo_zones.add(self.commune)

    def create_detection(self, geometry, tile_set):
        return DetectionService.create_detection(
            geometry=geometry,
            user=self.user,
            tile_set_uuid=str(tile_set.uuid),
            detection_object_data={"object_type_uuid": str(self.object_type.uuid)},
        )

    def test_rejects_geometry_outside_tile_set_coverage(self):
        with self.assertRaises(ValueError) as ctx:
            self.create_detection(far_geometry(), self.tile_set)
        # the guard must be what rejects it — a far geometry also fails the later
        # z19-tile lookup with a ValueError, which would mask a deleted guard
        self.assertIn(COVERAGE_ERROR, str(ctx.exception))

    def test_accepts_geometry_inside_tile_set_coverage(self):
        # z19 slippy tile containing the Montpellier geometry's centroid
        create_tile(x=267794, y=191428, z=19)

        detection = self.create_detection(montpellier_geometry(), self.tile_set)

        self.assertEqual(detection.tile_set_id, self.tile_set.id)
        self.assertEqual(detection.detection_object.commune_id, self.commune.id)

    def test_zoneless_tile_set_is_not_guarded(self):
        # A tile set with no geo_zones keeps its previous behaviour (guard skipped);
        # far geometry then fails later (no z19 tile), NOT on the coverage check.
        zoneless = create_tile_set(name="Zoneless 2024")
        with self.assertRaises(ValueError) as ctx:
            self.create_detection(far_geometry(), zoneless)
        self.assertNotIn(COVERAGE_ERROR, str(ctx.exception))

    def test_associates_covering_custom_zone_without_geo_zones_link(self):
        # Regression: a custom zone whose geometry covers the detection must be
        # associated on insert even when its geo_zones M2M does not list the
        # detection's commune / department / region (a hand-drawn zone with no
        # collectivities, or a ZAE zone straddling a department border). The old
        # geo_zones__id__in pre-filter silently dropped these. `covers` still gates:
        # a zone that does not cover the detection stays unassociated.
        create_tile(x=267794, y=191428, z=19)

        covering_zone = GeoCustomZone.objects.create(
            name="Covering zone",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.89, 43.62),
        )  # deliberately no geo_zones association
        far_zone = GeoCustomZone.objects.create(
            name="Far zone",
            geometry=self.create_bbox_polygon(4.10, 43.60, 4.12, 43.62),
        )

        detection = self.create_detection(montpellier_geometry(), self.tile_set)

        associated = set(
            detection.detection_object.geo_custom_zones.values_list("id", flat=True)
        )
        self.assertIn(covering_zone.id, associated)
        self.assertNotIn(far_zone.id, associated)

    def test_null_geometry_zones_are_not_guarded(self):
        # GeoZone.geometry is nullable; a tile set whose only zones lack a geometry
        # must behave like a zoneless one, not reject every detection.
        null_geometry_commune = GeoCommune.objects.create(
            name="Sans géométrie",
            iso_code="34999",
            department=self.commune.department,
            geometry=None,
        )
        tile_set = create_tile_set(name="Null geometry 2024")
        tile_set.geo_zones.add(null_geometry_commune)

        with self.assertRaises(ValueError) as ctx:
            self.create_detection(far_geometry(), tile_set)
        self.assertNotIn(COVERAGE_ERROR, str(ctx.exception))
