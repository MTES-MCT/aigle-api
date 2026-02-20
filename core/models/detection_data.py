from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.historied import HistoriedModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from simple_history.models import HistoricalRecords

from core.models.user import User


class DetectionControlStatus(models.TextChoices):
    NOT_CONTROLLED = "NOT_CONTROLLED", "NOT_CONTROLLED"
    CONTROLLED_FIELD = "CONTROLLED_FIELD", "CONTROLLED_FIELD"
    PRIOR_LETTER_SENT = "PRIOR_LETTER_SENT", "PRIOR_LETTER_SENT"
    OFFICIAL_REPORT_DRAWN_UP = "OFFICIAL_REPORT_DRAWN_UP", "OFFICIAL_REPORT_DRAWN_UP"
    OBSERVARTION_REPORT_REDACTED = (
        "OBSERVARTION_REPORT_REDACTED",
        "OBSERVARTION_REPORT_REDACTED",
    )
    ADMINISTRATIVE_CONSTRAINT = "ADMINISTRATIVE_CONSTRAINT", "ADMINISTRATIVE_CONSTRAINT"
    REHABILITATED = "REHABILITATED", "REHABILITATED"


class DetectionValidationStatus(models.TextChoices):
    DETECTED_NOT_VERIFIED = "DETECTED_NOT_VERIFIED", "DETECTED_NOT_VERIFIED"
    SUSPECT = "SUSPECT", "SUSPECT"
    LEGITIMATE = "LEGITIMATE", "LEGITIMATE"
    INVALIDATED = "INVALIDATED", "INVALIDATED"


class DetectionValidationStatusChangeReason(models.TextChoices):
    SITADEL = "SITADEL", "SITADEL"
    EXTERNAL_API = "EXTERNAL_API", "EXTERNAL_API"
    IMPORT_FROM_LUCCA = "IMPORT_FROM_LUCCA", "IMPORT_FROM_LUCCA"


class DetectionPrescriptionStatus(models.TextChoices):
    PRESCRIBED = "PRESCRIBED", "PRESCRIBED"
    NOT_PRESCRIBED = "NOT_PRESCRIBED", "NOT_PRESCRIBED"


class DetectionData(TimestampedModelMixin, UuidModelMixin, DeletableModelMixin):
    detection_control_status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=DetectionControlStatus.choices,
    )
    detection_validation_status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=DetectionValidationStatus.choices,
    )
    detection_prescription_status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=DetectionPrescriptionStatus.choices,
        null=True,
    )
    user_last_update = models.ForeignKey(
        User,
        related_name="detection_datas_last_updated",
        on_delete=models.SET_NULL,
        null=True,
    )

    official_report_date = models.DateField(
        null=True
    )  # can be set if detection_control_status is OFFICIAL_REPORT_DRAWN_UP
    detection_validation_status_change_reason = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=DetectionValidationStatusChangeReason.choices,
        null=True,
    )

    history = HistoricalRecords(
        bases=[HistoriedModelMixin], cascade_delete_history=True
    )

    def set_detection_control_status(self, value: DetectionControlStatus):
        self.detection_control_status = value

        if (
            value != DetectionControlStatus.NOT_CONTROLLED
            and self.detection_validation_status
            == DetectionValidationStatus.DETECTED_NOT_VERIFIED
        ):
            self.detection_validation_status = DetectionValidationStatus.SUSPECT

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + [
            models.Index(fields=["detection_validation_status"]),
            models.Index(fields=["detection_control_status"]),
            models.Index(fields=["detection_prescription_status"]),
            models.Index(
                fields=[
                    "detection_validation_status",
                    "detection_control_status",
                    "detection_prescription_status",
                ],
            ),
        ]
