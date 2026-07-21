from django.db.models import Q
from rest_framework.exceptions import ValidationError

from core.models.detection import DetectionSource
from core.models.detection_data import DetectionPrescriptionStatus


BOOLEAN_CHOICES = (("false", "False"), ("true", "True"), ("null", "Null"))
INTERFACE_DRAWN_CHOICES = (
    ("ALL", "ALL"),
    ("INSIDE_SELECTED_ZONES", "INSIDE_SELECTED_ZONES"),
    ("NONE", "NONE"),
)


def require_custom_zones(data) -> None:
    """At least one zone à enjeux must be selected to list detections — detections
    outside every custom zone (zones urbaines) must never be shown. The frontend
    enforces this too (last zone can't be unticked)."""
    if not data.get("customZonesUuids"):
        raise ValidationError(
            {"customZonesUuids": ["Au moins une zone à enjeux doit être sélectionnée."]}
        )


def filter_score(queryset, name, value):
    if not value:
        return queryset

    return queryset.filter(
        Q(score__gte=value)
        | Q(
            detection_source__in=[
                DetectionSource.INTERFACE_DRAWN,
                DetectionSource.INTERFACE_FORCED_VISIBLE,
            ]
        )
    )


def filter_prescripted(queryset, name, value):
    if value == "null":
        return queryset

    if value == "true":
        return queryset.filter(
            detection_data__detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED
        )

    return queryset.filter(
        Q(
            detection_data__detection_prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED
        )
        | Q(detection_data__detection_prescription_status=None)
    )


def filter_custom_zones_uuids(data, queryset):
    custom_zones_uuids = (
        data.get("customZonesUuids").split(",") if data.get("customZonesUuids") else []
    )

    if custom_zones_uuids:
        if data.get("interfaceDrawn") == "ALL":
            queryset = queryset.filter(
                Q(detection_object__geo_custom_zones__uuid__in=custom_zones_uuids)
                | Q(
                    detection_source__in=[
                        DetectionSource.INTERFACE_DRAWN,
                    ]
                )
            )

        if not data.get("interfaceDrawn") or data.get("interfaceDrawn") in [
            "INSIDE_SELECTED_ZONES",
            "NONE",
        ]:
            queryset = queryset.filter(
                detection_object__geo_custom_zones__uuid__in=custom_zones_uuids
            )

    if data.get("interfaceDrawn") == "NONE":
        queryset = queryset.exclude(
            detection_source__in=[
                DetectionSource.INTERFACE_DRAWN,
            ]
        )

    return queryset
