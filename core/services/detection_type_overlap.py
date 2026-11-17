from collections import Counter
from dataclasses import dataclass, field
from typing import List

from django.db import connection, transaction
from django.utils import timezone

from core.constants.detection import PERCENTAGE_SAME_DETECTION_THRESHOLD
from core.models.detection_type_overlap_report import (
    DetectionTypeOverlapReport,
    DetectionTypeOverlapReportObjectType,
)
from core.models.geo_custom_zone import GeoCustomZoneStatus
from core.models.geo_zone import GeoZone
from core.models.object_type import ObjectType
from core.models.tile_set import TileSet, TileSetStatus, TileSetType

# A department holds ~1M detections per year among ~20M: the zone's are copied to an
# indexed temp table first. Against core_detection, the planner underestimates the zone
# filter and ANDs each GiST probe with a bitmap of the whole tile set (hours).
TEMP_TABLE = "detection_type_overlap"

CREATE_TEMP_TABLE_SQL = f"""
    CREATE TEMP TABLE {TEMP_TABLE} ON COMMIT DROP AS
    SELECT
        detection.geometry,
        ST_Area(detection.geometry) AS area,
        detection_object.object_type_id,
        EXISTS (
            SELECT 1
            FROM core_detectionobject_geo_custom_zones object_zone
            JOIN core_geocustomzone custom_zone
                ON custom_zone.geozone_ptr_id = object_zone.geocustomzone_id
            JOIN core_geozone custom_zone_base
                ON custom_zone_base.id = custom_zone.geozone_ptr_id
            WHERE object_zone.detectionobject_id = detection_object.id
                AND custom_zone.geo_custom_zone_status = %(active_status)s
                AND NOT custom_zone_base.deleted
        ) AS in_custom_zone
    FROM core_detection detection
    JOIN core_detectionobject detection_object
        ON detection_object.id = detection.detection_object_id
    CROSS JOIN (
        SELECT geometry FROM core_geozone WHERE id = %(geo_zone_id)s
    ) zone
    WHERE detection.tile_set_id = ANY(%(tile_set_ids)s)
        AND NOT detection.deleted
        AND NOT detection_object.deleted
        AND (zone.geometry IS NULL OR ST_Intersects(detection.geometry, zone.geometry))
"""

# Same overlap rule as DetectionService.get_linked_detections (intersection >= threshold
# of either detection's area, areas in SRID 4326 units), with a DIFFERENT object type.
# Grouped by the types each detection overlaps: a few hundred rows, tallied in Python.
TYPE_OVERLAP_GROUPS_SQL = f"""
    SELECT
        detection.in_custom_zone,
        detection.object_type_id,
        overlap.other_object_type_ids,
        COUNT(*)
    FROM {TEMP_TABLE} detection
    CROSS JOIN LATERAL (
        SELECT
            array_agg(
                DISTINCT other.object_type_id ORDER BY other.object_type_id
            ) AS other_object_type_ids
        FROM {TEMP_TABLE} other
        WHERE other.object_type_id <> detection.object_type_id
            AND ST_Intersects(other.geometry, detection.geometry)
            AND ST_Area(ST_Intersection(other.geometry, detection.geometry))
                >= %(threshold)s * LEAST(detection.area, other.area)
    ) overlap
    GROUP BY 1, 2, 3
"""


@dataclass
class DetectionTypeOverlapCounts:
    total: int = 0
    # overlapping a detection of another object type
    overlapping: int = 0
    # overlapping a detection of another object type, one of the two being prescribable
    overlapping_prescribable: int = 0
    # prescribable object type id -> detections overlapping a detection of another
    # object type, one of the two being of this type
    overlapping_by_object_type: Counter = field(default_factory=Counter)

    def __add__(self, other: "DetectionTypeOverlapCounts"):
        return DetectionTypeOverlapCounts(
            total=self.total + other.total,
            overlapping=self.overlapping + other.overlapping,
            overlapping_prescribable=self.overlapping_prescribable
            + other.overlapping_prescribable,
            overlapping_by_object_type=self.overlapping_by_object_type
            + other.overlapping_by_object_type,
        )


@dataclass
class DetectionTypeOverlapIndicator:
    tile_sets: List[TileSet]
    prescribable_object_types: List[ObjectType]
    in_custom_zones: DetectionTypeOverlapCounts = field(
        default_factory=DetectionTypeOverlapCounts
    )
    outside_custom_zones: DetectionTypeOverlapCounts = field(
        default_factory=DetectionTypeOverlapCounts
    )

    @property
    def all(self) -> DetectionTypeOverlapCounts:
        return self.in_custom_zones + self.outside_custom_zones


class DetectionTypeOverlapService:
    @staticmethod
    def get_latest_tile_sets(geo_zone: GeoZone) -> List[TileSet]:
        """The BACKGROUND tile sets linked to the zone with the most recent year."""
        tile_sets = (
            TileSet.objects.filter(
                geo_zones=geo_zone,
                tile_set_type=TileSetType.BACKGROUND,
                deleted=False,
            )
            .exclude(tile_set_status=TileSetStatus.DEACTIVATED)
            .order_by("-date", "id")
        )
        latest_tile_set = tile_sets.first()
        if not latest_tile_set:
            return []

        return list(tile_sets.filter(date__year=latest_tile_set.date.year))

    @staticmethod
    def get_prescribable_object_types() -> List[ObjectType]:
        # 0 counts as not prescribable, as in PrescriptionService
        return list(
            ObjectType.objects.filter(
                prescription_duration_years__gt=0, deleted=False
            ).order_by("name")
        )

    @staticmethod
    def compute_indicator(geo_zone: GeoZone) -> DetectionTypeOverlapIndicator:
        tile_sets = DetectionTypeOverlapService.get_latest_tile_sets(geo_zone)
        prescribable_object_types = (
            DetectionTypeOverlapService.get_prescribable_object_types()
        )
        indicator = DetectionTypeOverlapIndicator(
            tile_sets=tile_sets, prescribable_object_types=prescribable_object_types
        )
        if not tile_sets:
            return indicator

        params = {
            "geo_zone_id": geo_zone.id,
            "tile_set_ids": [tile_set.id for tile_set in tile_sets],
            "active_status": GeoCustomZoneStatus.ACTIVE.value,
            "threshold": PERCENTAGE_SAME_DETECTION_THRESHOLD,
        }
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {TEMP_TABLE}")
            cursor.execute(CREATE_TEMP_TABLE_SQL, params)
            cursor.execute(f"CREATE INDEX ON {TEMP_TABLE} USING GIST (geometry)")
            cursor.execute(f"ANALYZE {TEMP_TABLE}")
            cursor.execute(TYPE_OVERLAP_GROUPS_SQL, params)
            rows = cursor.fetchall()
            cursor.execute(f"DROP TABLE {TEMP_TABLE}")

        prescribable_ids = {object_type.id for object_type in prescribable_object_types}
        for in_custom_zone, object_type_id, other_object_type_ids, count in rows:
            counts = (
                indicator.in_custom_zones
                if in_custom_zone
                else indicator.outside_custom_zones
            )
            counts.total += count
            # array_agg over no row is NULL: no overlap
            if not other_object_type_ids:
                continue

            counts.overlapping += count
            involved_prescribable_ids = prescribable_ids & {
                object_type_id,
                *other_object_type_ids,
            }
            if involved_prescribable_ids:
                counts.overlapping_prescribable += count
            for prescribable_id in involved_prescribable_ids:
                counts.overlapping_by_object_type[prescribable_id] += count

        return indicator

    @staticmethod
    @transaction.atomic()
    def save_report(
        geo_zone: GeoZone, indicator: DetectionTypeOverlapIndicator
    ) -> DetectionTypeOverlapReport:
        """Create the zone's report, or replace the one it already has."""
        all_counts = indicator.all
        custom_zones_counts = indicator.in_custom_zones
        report, _ = DetectionTypeOverlapReport.objects.update_or_create(
            geo_zone=geo_zone,
            defaults={
                "report_date": timezone.now(),
                "detections_count": all_counts.total,
                "overlapping_count": all_counts.overlapping,
                "overlapping_prescribable_count": all_counts.overlapping_prescribable,
                "custom_zones_detections_count": custom_zones_counts.total,
                "custom_zones_overlapping_count": custom_zones_counts.overlapping,
                "custom_zones_overlapping_prescribable_count": (
                    custom_zones_counts.overlapping_prescribable
                ),
            },
        )
        report.tile_sets.set(indicator.tile_sets)
        report.object_types.all().delete()
        DetectionTypeOverlapReportObjectType.objects.bulk_create(
            [
                DetectionTypeOverlapReportObjectType(
                    report=report,
                    object_type=object_type,
                    overlapping_count=all_counts.overlapping_by_object_type[
                        object_type.id
                    ],
                    custom_zones_overlapping_count=(
                        custom_zones_counts.overlapping_by_object_type[object_type.id]
                    ),
                )
                for object_type in indicator.prescribable_object_types
            ]
        )
        return report
