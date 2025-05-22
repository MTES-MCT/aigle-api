from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_zone import GeoZone
from django.db import models


class GeoSubCustomZone(GeoZone):
    custom_zone = models.ForeignKey(
        GeoCustomZone, related_name="sub_custom_zones", on_delete=models.CASCADE
    )

    class Meta:
        indexes = [
            models.Index(fields=["geozone_ptr"]),
        ]
