"""Tests for the `compute_detection_type_overlaps` command and its service."""

import datetime
from collections import Counter

from django.contrib.gis.geos import Polygon
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from core.models.detection_type_overlap_report import DetectionTypeOverlapReport
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.geo_region import GeoRegion
from core.models.tile_set import TileSetStatus, TileSetType
from core.services.detection_type_overlap import (
    DetectionTypeOverlapCounts,
    DetectionTypeOverlapService,
)
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_object,
    create_object_type,
    create_tile_set,
)

SIZE = 0.001


def square(x):
    return Polygon.from_bbox((x, 43.5, x + SIZE, 43.5 + SIZE))


class ComputeDetectionTypeOverlapsTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.zone = GeoRegion.objects.create(
            name="Region",
            insee_code="overlap-test",
            surface_km2=1,
            geometry=Polygon.from_bbox((3.0, 43.0, 4.0, 44.0)),
        )
        self.hard = create_object_type(
            name="Construction en dur", prescription_duration_years=10
        )
        self.pool = create_object_type(name="Piscine", prescription_duration_years=10)
        self.mobile_home = create_object_type(name="Mobil-home")
        self.caravan = create_object_type(name="Caravane")
        self.boat = create_object_type(name="Bateau", prescription_duration_years=0)

        self.old = self._tile_set("2023", datetime.date(2023, 6, 1))
        self.latest = self._tile_set("2024", datetime.date(2024, 6, 1))
        self._tile_set(
            "2025 deactivated",
            datetime.date(2025, 6, 1),
            tile_set_status=TileSetStatus.DEACTIVATED,
        )
        self._tile_set(
            "2025 indicative",
            datetime.date(2025, 6, 1),
            tile_set_type=TileSetType.INDICATIVE,
        )
        self.unlinked = create_tile_set(name="2024 other zone", date=self.latest.date)

        self.active_zone = GeoCustomZone.objects.create(
            name="ZAE", geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE
        )
        self.inactive_zone = GeoCustomZone.objects.create(
            name="ZAE off", geo_custom_zone_status=GeoCustomZoneStatus.INACTIVE
        )

    def _tile_set(self, name, date, **kwargs):
        tile_set = create_tile_set(name=name, date=date, **kwargs)
        tile_set.geo_zones.add(self.zone)
        return tile_set

    def _detection(self, object_type, x, tile_set=None, custom_zone=None):
        detection_object = create_detection_object(object_type=object_type)
        if custom_zone:
            detection_object.geo_custom_zones.add(custom_zone)
        return create_detection(
            detection_object=detection_object,
            tile_set=tile_set or self.latest,
            geometry=square(x),
        )

    def _create_scenario(self):
        # 80 % overlap, construction en dur vs mobil-home
        self._detection(self.hard, 3.5, custom_zone=self.active_zone)
        self._detection(self.mobile_home, 3.5002)
        # 70 % overlap, piscine vs mobil-home
        self._detection(self.pool, 3.51, custom_zone=self.active_zone)
        self._detection(self.mobile_home, 3.5103)
        # overlaps between types that are not prescribable (0 years counts as not)
        self._detection(self.caravan, 3.56)
        self._detection(self.mobile_home, 3.5602)
        self._detection(self.boat, 3.58)
        self._detection(self.mobile_home, 3.5802)
        # three types overlapping each other, two of them prescribable
        self._detection(self.mobile_home, 3.57)
        self._detection(self.hard, 3.5701)
        self._detection(self.pool, 3.5702)
        # alone, in a deactivated zone (does not count as ZAE)
        self._detection(self.pool, 3.52, custom_zone=self.inactive_zone)
        # same type overlap, plus another type in a tile set not linked to the zone
        self._detection(self.pool, 3.53)
        self._detection(self.pool, 3.5302)
        self._detection(self.mobile_home, 3.53, tile_set=self.unlinked)
        # 20 % overlap: under the threshold
        self._detection(self.hard, 3.54)
        self._detection(self.pool, 3.5408)
        # overlaps only detections of other years
        self._detection(self.hard, 3.55)
        self._detection(self.mobile_home, 3.55, tile_set=self.old)
        self._detection(
            self.mobile_home,
            3.55,
            tile_set=self._tile_set(
                "2025 partial",
                datetime.date(2025, 6, 1),
                tile_set_type=TileSetType.PARTIAL,
            ),
        )
        # outside the zone
        self._detection(self.hard, 5.0)
        self._detection(self.mobile_home, 5.0)

    def test_latest_tile_sets(self):
        partial = self._tile_set(
            "2025 partial",
            datetime.date(2025, 6, 1),
            tile_set_type=TileSetType.PARTIAL,
        )
        same_year = self._tile_set("2024 bis", datetime.date(2024, 1, 1))

        tile_sets = DetectionTypeOverlapService.get_latest_tile_sets(self.zone)

        self.assertCountEqual(tile_sets, [self.latest, same_year])
        self.assertNotIn(partial, tile_sets)

    def test_counts(self):
        self._create_scenario()

        indicator = DetectionTypeOverlapService.compute_indicator(geo_zone=self.zone)

        self.assertEqual(indicator.tile_sets, [self.latest])
        self.assertEqual(indicator.prescribable_object_types, [self.hard, self.pool])
        self.assertEqual(
            indicator.all,
            self._counts(17, 11, 7, hard=5, pool=5),
        )
        self.assertEqual(
            indicator.in_custom_zones,
            self._counts(2, 2, 2, hard=1, pool=1),
        )
        self.assertEqual(
            indicator.outside_custom_zones,
            self._counts(15, 9, 5, hard=4, pool=4),
        )

    def _counts(self, total, overlapping, overlapping_prescribable, hard, pool):
        return DetectionTypeOverlapCounts(
            total=total,
            overlapping=overlapping,
            overlapping_prescribable=overlapping_prescribable,
            overlapping_by_object_type=Counter(
                {self.hard.id: hard, self.pool.id: pool}
            ),
        )

    def test_command_logs_rates(self):
        self._detection(self.hard, 3.5, custom_zone=self.active_zone)
        self._detection(self.mobile_home, 3.5002)
        self._detection(self.pool, 3.52)
        self._detection(self.pool, 3.53)

        with self.assertLogs("aigle", level="INFO") as captured:
            call_command("compute_detection_type_overlaps", geozone_uuid=self.zone.uuid)

        output = "\n".join(captured.output)
        self.assertIn("2024 (2024-06-01)", output)
        self.assertIn(
            "Prescribable object types: Construction en dur (10 years), "
            "Piscine (10 years)",
            output,
        )
        self.assertIn("All | 4 detections", output)
        self.assertIn(
            "All | overlapping another type: 2 problematic, 2 without issue, "
            "rate 50.00 %",
            output,
        )
        self.assertIn(
            "All | overlapping another type, one being Piscine: 0 problematic, "
            "4 without issue, rate 0.00 %",
            output,
        )
        self.assertIn(
            "In zones à enjeux | overlapping another type, one being prescribable: "
            "1 problematic, 0 without issue, rate 100.00 %",
            output,
        )

    def test_command_unknown_geozone(self):
        with self.assertRaises(CommandError):
            call_command(
                "compute_detection_type_overlaps",
                geozone_uuid="00000000-0000-0000-0000-000000000000",
            )

    def test_command_saves_report(self):
        self._create_scenario()

        call_command("compute_detection_type_overlaps", geozone_uuid=self.zone.uuid)

        report = DetectionTypeOverlapReport.objects.get(geo_zone=self.zone)
        self.assertEqual(list(report.tile_sets.all()), [self.latest])
        self.assertEqual(
            (
                report.detections_count,
                report.overlapping_count,
                report.overlapping_prescribable_count,
                report.custom_zones_detections_count,
                report.custom_zones_overlapping_count,
                report.custom_zones_overlapping_prescribable_count,
            ),
            (17, 11, 7, 2, 2, 2),
        )
        self.assertCountEqual(
            report.object_types.values_list(
                "object_type", "overlapping_count", "custom_zones_overlapping_count"
            ),
            [(self.hard.id, 5, 1), (self.pool.id, 5, 1)],
        )

    def test_command_replaces_report(self):
        self._detection(self.hard, 3.5)
        self._detection(self.mobile_home, 3.5002)
        call_command("compute_detection_type_overlaps", geozone_uuid=self.zone.uuid)
        first = DetectionTypeOverlapReport.objects.get(geo_zone=self.zone)

        # a newer year, and an object type that is no longer prescribable
        self.pool.prescription_duration_years = None
        self.pool.save()
        newer = self._tile_set("2025", datetime.date(2025, 6, 1))
        self._detection(self.hard, 3.5, tile_set=newer)
        call_command("compute_detection_type_overlaps", geozone_uuid=self.zone.uuid)

        report = DetectionTypeOverlapReport.objects.get(geo_zone=self.zone)
        self.assertEqual(report.id, first.id)
        self.assertGreater(report.report_date, first.report_date)
        self.assertEqual(list(report.tile_sets.all()), [newer])
        self.assertEqual((report.detections_count, report.overlapping_count), (1, 0))
        self.assertEqual(
            list(report.object_types.values_list("object_type", flat=True)),
            [self.hard.id],
        )

    def test_command_without_tile_set_deletes_report(self):
        zone = GeoRegion.objects.create(
            name="Empty", insee_code="overlap-empty", surface_km2=1
        )
        DetectionTypeOverlapReport.objects.create(
            geo_zone=zone,
            report_date=timezone.now(),
            detections_count=1,
            overlapping_count=0,
            overlapping_prescribable_count=0,
            custom_zones_detections_count=0,
            custom_zones_overlapping_count=0,
            custom_zones_overlapping_prescribable_count=0,
        )

        # queued after every import, a zae one too: not an error
        call_command("compute_detection_type_overlaps", geozone_uuid=zone.uuid)

        self.assertFalse(
            DetectionTypeOverlapReport.objects.filter(geo_zone=zone).exists()
        )
