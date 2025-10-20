from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.historied import HistoriedModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from simple_history.models import HistoricalRecords

from core.models.detection_data import DetectionData
from core.models.user import User


class DetectionAuthorization(
    TimestampedModelMixin, UuidModelMixin, DeletableModelMixin
):
    authorization_date = models.DateField()
    authorization_id = models.CharField(null=True)
    detection_data = models.ForeignKey(
        DetectionData, related_name="detection_authorizations", on_delete=models.CASCADE
    )
