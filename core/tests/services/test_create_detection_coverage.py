from django.contrib.gis.geos import Polygon

from core.services.detection import DetectionService
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import create_object_type, create_tile_set
from core.tests.fixtures.geo_data import create_montpellier_commune
from core.tests.fixtures.users import create_super_admin


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

    def test_rejects_geometry_outside_tile_set_coverage(self):
        # ~9500 km from Montpellier (La Réunion) — cannot intersect the tile set coverage
        far_geometry = Polygon(
            [
                (55.5000, -20.9000),
                (55.5010, -20.9000),
                (55.5010, -20.8990),
                (55.5000, -20.8990),
                (55.5000, -20.9000),
            ],
            srid=4326,
        )
        with self.assertRaises(ValueError):
            DetectionService.create_detection(
                geometry=far_geometry,
                user=self.user,
                tile_set_uuid=str(self.tile_set.uuid),
                detection_object_data={"object_type_uuid": str(self.object_type.uuid)},
            )

    def test_zoneless_tile_set_is_not_guarded(self):
        # A tile set with no geo_zones keeps its previous behaviour (guard skipped);
        # far geometry then fails later (no z19 tile), NOT on the coverage check.
        zoneless = create_tile_set(name="Zoneless 2024")
        far_geometry = Polygon(
            [
                (55.5000, -20.9000),
                (55.5010, -20.9000),
                (55.5010, -20.8990),
                (55.5000, -20.8990),
                (55.5000, -20.9000),
            ],
            srid=4326,
        )
        with self.assertRaises(ValueError) as ctx:
            DetectionService.create_detection(
                geometry=far_geometry,
                user=self.user,
                tile_set_uuid=str(zoneless.uuid),
                detection_object_data={"object_type_uuid": str(self.object_type.uuid)},
            )
        self.assertNotIn("outside the tile set coverage", str(ctx.exception))
