import os
import tempfile
from datetime import datetime
from typing import Dict, Any
from django.http import HttpResponse, JsonResponse
from django.conf import settings

from core.models.detection_object import DetectionObject
from core.utils.logs import create_log, AnalyticLogType
from core.utils.odt_processor import ODTTemplateProcessor
from core.permissions.user import UserPermission
from core.permissions.geo_custom_zone import GeoCustomZonePermission
from rest_framework.status import HTTP_500_INTERNAL_SERVER_ERROR


class PriorLetterService:
    """Service for handling prior letter document generation."""

    TEMPLATE_PATH = getattr(
        settings, "PRIOR_LETTER_TEMPLATE_PATH", "templates/prior_letter.odt"
    )

    def __init__(self, user):
        self.user = user

    def generate_document(self, detection_object_uuid: str) -> HttpResponse:
        """Generate prior letter document for detection object."""
        # Get detection object with permissions check
        detection_object = self._get_detection_object_with_permissions(
            detection_object_uuid
        )

        # Update control status
        self._update_control_status(detection_object)

        # Create analytics log
        self._create_analytics_log(detection_object, detection_object_uuid)

        # Generate document
        return self._generate_odt_document(detection_object)

    def _get_detection_object_with_permissions(
        self, detection_object_uuid: str
    ) -> DetectionObject:
        """Retrieve detection object with permission validation."""
        geo_custom_zones_prefetch, geo_custom_zones_category_prefetch = (
            GeoCustomZonePermission(user=self.user).get_detection_object_prefetch()
        )

        queryset = DetectionObject.objects.prefetch_related(
            geo_custom_zones_prefetch,
            geo_custom_zones_category_prefetch,
        ).select_related("parcel", "parcel__commune", "object_type")

        try:
            detection_object = queryset.get(uuid=detection_object_uuid)
        except DetectionObject.DoesNotExist:
            raise PermissionError("Detection object not found or access denied")

        # Check edit permissions
        UserPermission(user=self.user).can_edit(
            geometry=detection_object.geometry, raise_exception=True
        )

        return detection_object

    def _update_control_status(self, detection_object: DetectionObject) -> None:
        """Update detection object control status with business rules."""
        # Import here to avoid circular imports
        from core.models.detection import DetectionControlStatus
        from core.models.detection_data import DetectionData

        # Business logic for status updates
        detections_to_update = []
        for detection in detection_object.detections.all():
            if detection.detection_data:
                detection.detection_data.detection_control_status = (
                    DetectionControlStatus.CONTROLLED
                )
                detection.detection_data.user_last_update = self.user
                detections_to_update.append(detection.detection_data)

        if detections_to_update:
            DetectionData.objects.bulk_update(
                detections_to_update, ["detection_control_status", "user_last_update"]
            )

    def _create_analytics_log(
        self, detection_object: DetectionObject, detection_object_uuid: str
    ) -> None:
        """Create analytics log for document generation."""
        create_log(
            self.user,
            AnalyticLogType.PRIOR_LETTER_DOWNLOAD,
            {
                "parcelUuid": str(detection_object.parcel.uuid)
                if detection_object.parcel
                else None,
                "detectionObjectUuid": str(detection_object_uuid),
            },
        )

    def _generate_odt_document(self, detection_object: DetectionObject) -> HttpResponse:
        """Generate ODT document from template."""
        try:
            parcel_label = self._get_parcel_label(detection_object)
            filename = f"Courrier préalable - {parcel_label}.odt"

            with tempfile.NamedTemporaryFile(suffix=".odt", delete=False) as temp_file:
                temp_output_path = temp_file.name

            try:
                # Process template
                processor = ODTTemplateProcessor(self.TEMPLATE_PATH)
                placeholders = self._build_template_placeholders(
                    detection_object, parcel_label
                )
                processor.replace_placeholders(placeholders, temp_output_path)

                # Generate response
                with open(temp_output_path, "rb") as f:
                    response = HttpResponse(
                        f.read(), content_type="application/vnd.oasis.opendocument.text"
                    )
                    response["content-disposition"] = (
                        f'attachment; filename="{filename}"'
                    )
                    return response
            finally:
                os.unlink(temp_output_path)

        except Exception as e:
            return JsonResponse(
                {"error": "Failed to generate document", "details": str(e)},
                status=HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _get_parcel_label(self, detection_object: DetectionObject) -> str:
        """Generate parcel label for filename."""
        if detection_object.parcel:
            return f"{detection_object.parcel.section} {detection_object.parcel.num_parcel}"
        return "[[Parcelle inconnue]]"

    def _build_template_placeholders(
        self, detection_object: DetectionObject, parcel_label: str
    ) -> Dict[str, Any]:
        """Build placeholders for document template."""
        return {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "num_parcelle": parcel_label,
            "nom_commune": detection_object.commune.name,
            "num_fiche_signalement": detection_object.id,
            "addresse_avec_parentheses": f"({detection_object.address})",
            "zones_a_enjeux": self._get_custom_zones_text(detection_object),
        }

    def _get_custom_zones_text(self, detection_object: DetectionObject) -> str:
        """Format custom zone names for document."""
        geo_custom_zones = detection_object.geo_custom_zones.all()
        geo_sub_custom_zones = detection_object.geo_sub_custom_zones.all()

        zones_names = []

        for zone in geo_custom_zones:
            if zone.geo_custom_zone_category:
                zones_names.append(zone.geo_custom_zone_category.name)

        for sub_zone in geo_sub_custom_zones:
            if (
                sub_zone.geo_custom_zone
                and sub_zone.geo_custom_zone.geo_custom_zone_category
            ):
                zones_names.append(
                    sub_zone.geo_custom_zone.geo_custom_zone_category.name
                )

        # Remove duplicates and sort
        unique_zones = sorted(set(zones_names))
        return ", ".join(unique_zones) if unique_zones else "Aucune zone à enjeux"
