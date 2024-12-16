from typing import List
from django.contrib.gis.db.models.aggregates import Union


from core.models.geo_zone import GeoZone


def get_geometry(
    communes_uuids: List[str],
    departments_uuids: List[str],
    regions_uuids: List[str],
):
    geozone_uuids = (
        (communes_uuids or []) + (departments_uuids or []) + (regions_uuids or [])
    )
    return GeoZone.objects.filter(uuid__in=geozone_uuids).aggregate(
        union_geometry=Union("geometry")
    )["union_geometry"]
