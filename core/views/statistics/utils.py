from typing import Optional
from django.db.models import Q
from django.contrib.gis.geos.collections import MultiPolygon

from core.models.detection_data import DetectionPrescriptionStatus


def get_detections_where_clauses(
    base_path_detection: str,
    endpoint_serializer,
    global_geometry: Optional[MultiPolygon],
):
    detections_where_clauses = Q()

    if global_geometry:
        detections_where_clauses = detections_where_clauses & Q(
            **{f"{base_path_detection}geometry__intersects": global_geometry}
        )

    if endpoint_serializer.validated_data.get("detectionValidationStatuses"):
        detections_where_clauses = detections_where_clauses & Q(
            **{
                f"{base_path_detection}detection_data__detection_validation_status__in": endpoint_serializer.validated_data[
                    "detectionValidationStatuses"
                ]
            }
        )

    if endpoint_serializer.validated_data.get("tileSetsUuids"):
        detections_where_clauses = detections_where_clauses & Q(
            **{
                f"{base_path_detection}tile_set__uuid__in": endpoint_serializer.validated_data[
                    "tileSetsUuids"
                ]
            }
        )

    if endpoint_serializer.validated_data.get("detectionControlStatuses"):
        detections_where_clauses = detections_where_clauses & Q(
            **{
                f"{base_path_detection}detection_data__detection_control_status__in": endpoint_serializer.validated_data[
                    "detectionControlStatuses"
                ]
            }
        )

    if (
        endpoint_serializer.validated_data.get("score")
        and endpoint_serializer.validated_data.get("score") > 0
    ):
        detections_where_clauses = detections_where_clauses & Q(
            **{
                f"{base_path_detection}score__gte": endpoint_serializer.validated_data[
                    "score"
                ]
            }
        )

    if endpoint_serializer.validated_data.get("objectTypesUuids"):
        detections_where_clauses = detections_where_clauses & Q(
            **{
                f"{base_path_detection}detection_object__object_type__uuid__in": endpoint_serializer.validated_data[
                    "objectTypesUuids"
                ]
            }
        )

    if endpoint_serializer.validated_data.get("customZonesUuids"):
        detections_where_clauses = detections_where_clauses & Q(
            **{
                f"{base_path_detection}detection_object__geo_custom_zones__uuid__in": endpoint_serializer.validated_data[
                    "customZonesUuids"
                ]
            }
        )

    if endpoint_serializer.validated_data.get("prescripted") is not None:
        if endpoint_serializer.validated_data.get("prescripted"):
            detections_where_clauses = detections_where_clauses & Q(
                **{
                    f"{base_path_detection}detection_data__detection_prescription_status": DetectionPrescriptionStatus.PRESCRIBED
                }
            )
        else:
            detections_where_clauses = detections_where_clauses & (
                Q(
                    **{
                        f"{base_path_detection}detection_data__detection_prescription_status": DetectionPrescriptionStatus.NOT_PRESCRIBED
                    }
                )
                | Q(
                    **{
                        f"{base_path_detection}detection_data__detection_prescription_status": None
                    }
                )
            )

    return detections_where_clauses
