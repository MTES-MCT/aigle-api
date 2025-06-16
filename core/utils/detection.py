from typing import Iterable, List

from core.models.detection import Detection
from django.contrib.gis.geos import GEOSGeometry

from django.contrib.gis.db.models.functions import Intersection, Area
from django.db.models import Value
from django.db.models import Q

from core.models.detection_object import DetectionObject
from core.models.tile_set import TileSetStatus, TileSetType


PERCENTAGE_SAME_DETECTION_THRESHOLD = 0.5


def get_linked_detections(
    detection_geometry: GEOSGeometry,
    object_type_id: int,
    exclude_tile_set_ids: Iterable[int],
) -> List[Detection]:
    linked_detections_queryset = Detection.objects

    linked_detections_queryset = linked_detections_queryset.filter(
        ~Q(tile_set__id__in=exclude_tile_set_ids)
    )
    linked_detections_queryset = linked_detections_queryset.order_by("-tile_set__date")
    linked_detections_queryset = linked_detections_queryset.filter(
        geometry__intersects=detection_geometry,
        detection_object__object_type__id=object_type_id,
    )
    linked_detections_queryset = linked_detections_queryset.annotate(
        intersection_area=Area(Intersection("geometry", Value(detection_geometry)))
    )
    linked_detections_queryset = linked_detections_queryset.order_by(
        "-intersection_area"
    )
    linked_detections_queryset = linked_detections_queryset.select_related(
        "detection_object", "detection_object__object_type", "tile_set"
    )

    # we filter out detections that have too small intersection area with the detection
    return list(
        [
            detection
            for detection in linked_detections_queryset.all()
            if detection.intersection_area.sq_m
            >= detection_geometry.area * PERCENTAGE_SAME_DETECTION_THRESHOLD
            or detection.intersection_area.sq_m
            >= detection.geometry.area * PERCENTAGE_SAME_DETECTION_THRESHOLD
        ]
    )


def get_most_recent_detection(detection_object: DetectionObject) -> Detection:
    return (
        detection_object.detections.exclude(
            tile_set__tile_set_status=TileSetStatus.DEACTIVATED
        )
        .filter(
            tile_set__tile_set_type__in=[TileSetType.BACKGROUND, TileSetType.PARTIAL]
        )
        .select_related("detection_data")
        .order_by("-tile_set__date")
        .first()
    )
