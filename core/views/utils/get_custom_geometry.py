import json
from typing import List
from django.http import JsonResponse

from rest_framework import serializers


from core.constants.geo import SRID
from core.constants.order_by import GEO_CUSTOM_ZONES_ORDER_BYS
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.serializers.geo_custom_zone import GeoCustomZoneGeoFeatureSerializer
from django.contrib.gis.geos import Polygon
from django.contrib.gis.db.models.functions import Intersection
from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.geos import GEOSGeometry
from django.db.models.functions import Coalesce
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated


class GeometrySerializer(serializers.Serializer):
    neLat = serializers.FloatField()
    neLng = serializers.FloatField()
    swLat = serializers.FloatField()
    swLng = serializers.FloatField()

    uuids = serializers.CharField(required=False, allow_null=True)
    uuidsNegative = serializers.CharField(required=False, allow_null=True)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def endpoint(request):
    geometry_serializer = GeometrySerializer(data=request.GET)
    geometry_serializer.is_valid(raise_exception=True)

    polygon_requested = Polygon.from_bbox(
        (
            geometry_serializer.data["swLng"],
            geometry_serializer.data["swLat"],
            geometry_serializer.data["neLng"],
            geometry_serializer.data["neLat"],
        )
    )
    polygon_requested.srid = SRID

    custom_zones = []

    if geometry_serializer.data.get("uuids"):
        queryset = get_queryset_geocustomzone(
            uuids=geometry_serializer.data["uuids"].split(","),
            polygon_requested=polygon_requested,
        )

        custom_zones = queryset.all()

    geometry_negative = []

    if geometry_serializer.data.get("uuidsNegative"):
        queryset_covered = get_queryset_geocustomzone(
            uuids=geometry_serializer.data["uuidsNegative"].split(","),
            polygon_requested=polygon_requested,
        )
        geometry_covered = queryset_covered.aggregate(union_geometry=Union("geometry"))[
            "union_geometry"
        ]

        if geometry_covered:
            geometry_negative = polygon_requested.difference(geometry_covered)
        else:
            geometry_negative = polygon_requested

    return JsonResponse(
        {
            "customZones": GeoCustomZoneGeoFeatureSerializer(
                custom_zones, many=True
            ).data,
            "customZoneNegative": json.loads(GEOSGeometry(geometry_negative).geojson)
            if geometry_negative
            else None,
        }
    )


def get_queryset_geocustomzone(uuids: List[str], polygon_requested: Polygon):
    queryset = GeoCustomZone.objects.order_by(*GEO_CUSTOM_ZONES_ORDER_BYS)

    try:
        queryset = queryset.filter(uuid__in=uuids)
    except Exception:
        pass

    queryset = queryset.filter(geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE)
    queryset = queryset.filter(geometry__intersects=polygon_requested)
    queryset = queryset.select_related("geo_custom_zone_category")
    queryset = queryset.values("uuid", "geo_custom_zone_status", "geo_custom_zone_type")
    queryset = queryset.annotate(
        name=Coalesce("name", "geo_custom_zone_category__name"),
        color=Coalesce("color", "geo_custom_zone_category__color"),
    )
    queryset = queryset.annotate(geometry=Intersection("geometry", polygon_requested))

    return queryset


URL = "get-custom-geometry/"
