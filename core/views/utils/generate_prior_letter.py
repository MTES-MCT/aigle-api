from datetime import datetime
import os
import tempfile
from django.conf import settings
from django.http import HttpResponse, JsonResponse


from rest_framework.status import HTTP_500_INTERNAL_SERVER_ERROR
from django.core.exceptions import BadRequest

from core.models.analytic_log import AnalyticLogType
from core.models.detection_data import DetectionControlStatus
from core.models.detection_object import DetectionObject
from core.models.user import User
from core.permissions.geo_custom_zone import GeoCustomZonePermission
from core.permissions.user import UserPermission
from core.utils.analytic_log import create_log
from core.utils.detection import get_most_recent_detection
from core.utils.odt_processor import ODTTemplateProcessor
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

TEMPLATE_PATH = os.path.join(settings.MEDIA_ROOT, "templates", "prior_letter.odt")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def endpoint(request, detection_object_uuid):
    detection_object = get_detection_object(
        detection_object_uuid=detection_object_uuid, user=request.user
    )
    update_control_status(detection_object=detection_object, user=request.user)

    create_log(
        request.user,
        AnalyticLogType.PRIOR_LETTER_DOWNLOAD,
        {
            "parcelUuid": str(detection_object.parcel.uuid)
            if detection_object.parcel
            else None,
            "detectionObjectUuid": str(detection_object_uuid),
        },
    )

    try:
        parcel_label = (
            (f"{detection_object.parcel.section} {detection_object.parcel.num_parcel}")
            if detection_object.parcel
            else "[[Parcelle inconnue]]"
        )
        filename = f"Courrier préalable - {parcel_label}.odt"

        with tempfile.NamedTemporaryFile(suffix=".odt", delete=False) as temp_file:
            temp_output_path = temp_file.name

        try:
            processor = ODTTemplateProcessor(TEMPLATE_PATH)
            processor.replace_placeholders(
                {
                    "date": datetime.now().strftime("%d/%m/%Y"),
                    "num_parcelle": parcel_label,
                    "nom_commune": detection_object.commune.name,
                    "num_fiche_signalement": detection_object.id,
                    "addresse_avec_parentheses": f"({detection_object.address})",
                    "zones_a_enjeux": get_custom_zones_text(detection_object),
                },
                temp_output_path,
            )

            with open(temp_output_path, "rb") as f:
                response = HttpResponse(
                    f.read(), content_type="application/vnd.oasis.opendocument.text"
                )
                response["content-disposition"] = f'attachment; filename="{filename}"'
                return response
        finally:
            os.unlink(temp_output_path)

    except Exception as e:
        return JsonResponse(
            {"error": "Failed to generate document", "details": str(e)},
            status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


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

    return f" et située en zones {
        ", ".join(zone_names)
    }"


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

    detection = get_most_recent_detection(detection_object)

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
