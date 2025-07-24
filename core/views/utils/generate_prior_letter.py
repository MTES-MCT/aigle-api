import os
from django.conf import settings


from django.core.exceptions import BadRequest

from core.models.detection_data import DetectionControlStatus
from core.models.detection_object import DetectionObject
from core.models.user import User
from core.permissions.geo_custom_zone import GeoCustomZonePermission
from core.permissions.user import UserPermission
from core.services.detection import DetectionService
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

TEMPLATE_PATH = os.path.join(settings.MEDIA_ROOT, "templates", "prior_letter.odt")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def endpoint(request, detection_object_uuid):
    from core.services.prior_letter import PriorLetterService

    service = PriorLetterService(user=request.user)
    return service.generate_document(detection_object_uuid)


def get_custom_zones_text(detection_object: DetectionObject):
    if not detection_object.geo_custom_zones:
        return ""

    zone_names = []

    for geo_custom_zone in detection_object.geo_custom_zones.all():
        if geo_custom_zone.geo_custom_zone_category:
            zone_names.append(
                geo_custom_zone.geo_custom_zone_category.name_short
                or geo_custom_zone.geo_custom_zone_category.name
            )
            continue

        zone_names.append(geo_custom_zone.name_short or geo_custom_zone.name)

    return ", ".join(zone_names)


def get_detection_object(detection_object_uuid: str, user: User):
    detection_object_qs = DetectionObject.objects.filter(uuid=detection_object_uuid)
    geo_custom_zones_prefetch, geo_custom_zones_category_prefetch = (
        GeoCustomZonePermission(user=user).get_detection_object_prefetch()
    )
    detection_object_qs = detection_object_qs.select_related("parcel", "commune")
    detection_object_qs = detection_object_qs.prefetch_related(
        geo_custom_zones_prefetch,
        geo_custom_zones_category_prefetch,
        "detections",
        "detections__tile_set",
    )

    detection_object = detection_object_qs.first()

    if not detection_object:
        raise BadRequest("Detection object not found")

    return detection_object


def update_control_status(detection_object: DetectionObject, user: User):
    if not UserPermission(user=user).can_edit(
        geometry=detection_object.detections.first().geometry, raise_exception=True
    ):
        return

    detection = DetectionService.get_most_recent_detection(
        detection_object=detection_object
    )

    if detection.detection_data.detection_control_status in [
        DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
        DetectionControlStatus.OBSERVARTION_REPORT_REDACTED,
        DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
        DetectionControlStatus.REHABILITATED,
    ]:
        return

    detection.detection_data.detection_control_status = (
        DetectionControlStatus.PRIOR_LETTER_SENT
    )
    detection.detection_data.save()


URL = "generate-prior-letter/<uuid:detection_object_uuid>/"
