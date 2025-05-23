from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH
from core.models.geo_department import GeoDepartment
from core.models.geo_epci import GeoEpci
from core.models.geo_zone import GeoZone


class GeoCommune(GeoZone):
    iso_code = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True)
    department = models.ForeignKey(
        GeoDepartment, related_name="communes", on_delete=models.CASCADE
    )
    epci = models.ForeignKey(
        GeoEpci, related_name="communes", on_delete=models.CASCADE, null=True
    )
