from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH
from core.models.geo_department import GeoDepartment

from core.models.geo_zone import GeoZone


class GeoEpci(GeoZone):
    siren_code = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True)
    department = models.ForeignKey(
        GeoDepartment, related_name="epcis", on_delete=models.CASCADE
    )
