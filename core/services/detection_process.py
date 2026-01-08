from datetime import datetime, date
from typing import List, Literal, Union

from core.models.detection import Detection, DetectionSource
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.models.detection_object import DetectionObject
from core.models.tile import TILE_DEFAULT_ZOOM, Tile
from django.contrib.gis.geos import MultiPolygon

from django.db.models import Prefetch, Sum, Case, When, IntegerField
from django.contrib.gis.db.models.functions import Centroid


class DetectionProcessService:
    """Service for handling detection database processes"""

    @staticmethod
    def merge_double_detections(tile_set_id: int):
        detection_objects = (
            DetectionObject.objects.annotate(
                detections_count=Sum(
                    Case(
                        When(detections__tile_set__id=tile_set_id, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                )
            )
            .filter(detections__tile_set__id=tile_set_id, detections_count__gt=1)
            .prefetch_related(
                Prefetch(
                    "detections",
                    queryset=Detection.objects.filter(
                        tile_set__id=tile_set_id,
                    ),
                ),
                "detections__tile_set",
                "detections__tile",
                "detections__detection_data",
            )
            .defer("detections__tile__geometry")
        )

        for detection_object in detection_objects.all():
            detections = detection_object.detections.all()
            detections_data = [detection.detection_data for detection in detections]
            detection_to_keep = max(detections, key=lambda detec: detec.score)

            # combine geometries
            union_geometry = MultiPolygon(
                [detec.geometry for detec in detections]
            ).unary_union
            new_geometry = union_geometry.envelope
            detection_to_keep.geometry = new_geometry

            # extract properties to keep the highest priority ones
            detection_to_keep.detection_source = extract_higest_priority_value(
                detections, "detection_source"
            )
            detection_to_keep.detection_data.set_detection_control_status(
                extract_higest_priority_value(
                    detections_data, "detection_control_status"
                )
            )
            detection_to_keep.detection_data.detection_validation_status = (
                extract_higest_priority_value(
                    detections_data, "detection_validation_status"
                )
            )
            detection_to_keep.detection_data.detection_prescription_status = (
                extract_higest_priority_value(
                    detections_data, "detection_prescription_status"
                )
            )

            # prescription
            detection_to_keep.auto_prescribed = any(
                [detection.auto_prescribed for detection in detections]
            )

            # tile: if all detections are associated to same tile, we do not change anything
            if not all(
                detection.tile.id == detections[0].tile.id for detection in detections
            ):
                centroid = Centroid(new_geometry)
                tile = Tile.objects.filter(
                    geometry__contains=centroid, z=TILE_DEFAULT_ZOOM
                ).first()

                if not tile:
                    print("TILE NOT FOUND")

                if tile:
                    detection_to_keep.tile = tile

            # user last update
            detection_last_updated = max(
                detections,
                key=lambda detec: detec.detection_data.updated_at or datetime.min,
            )
            detection_to_keep.detection_data.updated_at = (
                detection_last_updated.detection_data.updated_at
            )
            detection_to_keep.detection_data.user_last_update = (
                detection_last_updated.detection_data.user_last_update
            )

            # official_report_date
            if not all(
                detection.detection_data.official_report_date is None
                for detection in detections
            ):
                detection_to_keep.detection_data.official_report_date = max(
                    [
                        detection.detection_data.official_report_date or date.min
                        for detection in detections
                    ]
                )

            detection_to_keep.detection_data.save()
            detection_to_keep.save()

            detection_ids_to_delete = [
                detection.id
                for detection in detections
                if detection.id != detection_to_keep.id
            ]
            detection_data_ids_to_delete = [
                detection.detection_data.id
                for detection in detections
                if detection.id != detection_to_keep.id
            ]

            DetectionData.objects.filter(
                id__in=detection_data_ids_to_delete
            ).all().delete()
            Detection.objects.filter(id__in=detection_ids_to_delete).all().delete()


VALUE_PRIORITY_MAP = {
    "detection_source": {
        DetectionSource.INTERFACE_FORCED_VISIBLE: 0,
        DetectionSource.INTERFACE_DRAWN: 1,
        DetectionSource.ANALYSIS: 2,
    },
    "detection_control_status": {
        DetectionControlStatus.REHABILITATED: 0,
        DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT: 1,
        DetectionControlStatus.OBSERVARTION_REPORT_REDACTED: 2,
        DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP: 3,
        DetectionControlStatus.PRIOR_LETTER_SENT: 4,
        DetectionControlStatus.CONTROLLED_FIELD: 5,
        DetectionControlStatus.NOT_CONTROLLED: 6,
    },
    "detection_validation_status": {
        DetectionValidationStatus.INVALIDATED: 0,
        DetectionValidationStatus.LEGITIMATE: 1,
        DetectionValidationStatus.SUSPECT: 2,
        DetectionValidationStatus.DETECTED_NOT_VERIFIED: 3,
    },
    "detection_prescription_status": {
        DetectionPrescriptionStatus.PRESCRIBED: 0,
        DetectionPrescriptionStatus.NOT_PRESCRIBED: 1,
    },
}


def extract_higest_priority_value(
    items: List[Union[Detection, DetectionData]],
    property: Literal[
        "detection_source",
        "detection_control_status",
        "detection_validation_status",
        "detection_prescription_status",
    ],
):
    highest_priority_item = min(
        items,
        key=lambda item: VALUE_PRIORITY_MAP[property].get(getattr(item, property), 999),
    )
    return getattr(highest_priority_item, property)
