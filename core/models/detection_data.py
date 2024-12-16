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
    SIGNALED_COLLECTIVITY = "SIGNALED_COLLECTIVITY", "SIGNALED_COLLECTIVITY"
    SIGNALED_COMMUNE = "SIGNALED_COMMUNE", "SIGNALED_COMMUNE"
    CONTROLLED_FIELD = "CONTROLLED_FIELD", "CONTROLLED_FIELD"
    PRIOR_LETTER_SENT = "PRIOR_LETTER_SENT", "PRIOR_LETTER_SENT"
    OFFICIAL_REPORT_DRAWN_UP = "OFFICIAL_REPORT_DRAWN_UP", "OFFICIAL_REPORT_DRAWN_UP"
    OBSERVARTION_REPORT_REDACTED = (
        "OBSERVARTION_REPORT_REDACTED",
        "OBSERVARTION_REPORT_REDACTED",
    )
    VERBALIZED = "VERBALIZED", "VERBALIZED"
    REHABILITATED = "REHABILITATED", "REHABILITATED"


class DetectionValidationStatus(models.TextChoices):
    DETECTED_NOT_VERIFIED = "DETECTED_NOT_VERIFIED", "DETECTED_NOT_VERIFIED"
    SUSPECT = "SUSPECT", "SUSPECT"
    LEGITIMATE = "LEGITIMATE", "LEGITIMATE"
    INVALIDATED = "INVALIDATED", "INVALIDATED"


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
    history = HistoricalRecords(bases=[HistoriedModelMixin])

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + [
            models.Index(fields=["detection_validation_status"]),
            models.Index(fields=["detection_control_status"]),
            models.Index(
                fields=["detection_validation_status", "detection_control_status"]
            ),
        ]
