from core.models.detection import Detection
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionValidationStatus,
    DetectionValidationStatusChangeReason,
)
from core.models.detection_object import DetectionObject
from core.models.geo_commune import GeoCommune
from core.models.parcel import Parcel
from django.db.models import Prefetch
from simple_history.utils import bulk_update_with_history
from django.core.exceptions import BadRequest


class ExternalApiService:
    """Service for handling external API business logic."""

    @staticmethod
    def update_control_status(
        insee_code: str,
        parcel_section: str,
        parcel_number: int,
        control_status: DetectionControlStatus,
    ):
        commune = GeoCommune.objects.filter(iso_code=insee_code).first()

        if not commune:
            raise BadRequest(
                f"La commune avec le code insee suivant est introuvable: {insee_code}"
            )

        parcel = (
            Parcel.objects.filter(
                commune=commune,
                section=parcel_section,
                num_parcel=parcel_number,
            )
            .prefetch_related(
                Prefetch(
                    "detection_objects",
                    queryset=DetectionObject.objects.exclude(
                        detections__detection_data__detection_validation_status=DetectionValidationStatus.INVALIDATED
                    ).prefetch_related(
                        Prefetch(
                            "detections",
                            queryset=Detection.objects.select_related(
                                "detection_data"
                            ).defer("geometry"),
                        )
                    ),
                )
            )
            .first()
        )

        if not parcel:
            raise BadRequest(
                f"La parcelle avec les valeurs suivantes est introuvable pour la commune {commune.name}: section {parcel_section}, numéro {parcel_number}"
            )

        if not parcel.detection_objects.count():
            raise BadRequest(
                f"La parcelle suivante a été trouvé mais ne contient aucune détection valide: commune {commune.name}, section {parcel_section}, numéro {parcel_number}"
            )

        detections_data_to_update = []

        for detection_object in parcel.detection_objects.all():
            for detection in detection_object.detections.all():
                detection_data = detection.detection_data
                detection_data.set_detection_control_status(control_status)
                detection_data.detection_validation_status_change_reason = (
                    DetectionValidationStatusChangeReason.EXTERNAL_API
                )

                detections_data_to_update.append(detection_data)

        bulk_update_with_history(
            detections_data_to_update,
            DetectionData,
            [
                "detection_control_status",
                "detection_validation_status_change_reason",
                "detection_validation_status",
            ],
        )
