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
    # SET_NULL, not CASCADE: EPCI membership is a label on the commune, not its
    # existence. Cascading would delete the communes — and their parcels and detection
    # objects — when an EPCI is removed or re-imported.
    epci = models.ForeignKey(
        GeoEpci, related_name="communes", on_delete=models.SET_NULL, null=True
    )
