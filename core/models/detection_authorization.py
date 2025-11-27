from django.db import models


from common.models.deletable import DeletableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin

from core.models.detection_data import DetectionData


class DetectionAuthorization(
    TimestampedModelMixin, UuidModelMixin, DeletableModelMixin
):
    authorization_date = models.DateField()
    authorization_id = models.CharField(null=True)
    detection_data = models.ForeignKey(
        DetectionData, related_name="detection_authorizations", on_delete=models.CASCADE
    )
