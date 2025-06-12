from rest_framework.response import Response
from common.views.base import BaseViewSetMixin


from rest_framework import serializers
from core.constants.geo import SRID
from core.constants.order_by import GEO_CUSTOM_ZONES_ORDER_BYS
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.serializers.geo_custom_zone import (
    GeoCustomZoneGeoFeatureSerializer,
    GeoCustomZoneInputSerializer,
    GeoCustomZoneSerializer,
    GeoCustomZoneWithCollectivitiesSerializer,
)
from django_filters import FilterSet, CharFilter

from rest_framework.decorators import action

from core.utils.permissions import AdminRolePermission
from django.contrib.gis.geos import Polygon
from django.contrib.gis.db.models.functions import Intersection


class GeometrySerializer(serializers.Serializer):
    neLat = serializers.FloatField()
    neLng = serializers.FloatField()
    swLat = serializers.FloatField()
    swLng = serializers.FloatField()

    uuids = serializers.CharField(required=False, allow_null=True)


class GeoCustomZoneFilter(FilterSet):
    q = CharFilter(method="search")

    class Meta:
        model = GeoCustomZone
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(name__icontains=value)


class GeoCustomZoneViewSet(BaseViewSetMixin[GeoCustomZone]):
    filterset_class = GeoCustomZoneFilter
    permission_classes = [AdminRolePermission]

    def get_serializer_class(self):
        if self.action in ["create", "partial_update", "update"]:
            return GeoCustomZoneInputSerializer

        if self.action in ["retrieve"]:
            if self.request.GET.get("geometry"):
                return GeoCustomZoneGeoFeatureSerializer

        if self.request.GET.get("with_collectivities"):
            return GeoCustomZoneWithCollectivitiesSerializer

        return GeoCustomZoneSerializer

    def get_queryset(self):
        queryset = GeoCustomZone.objects.order_by(*GEO_CUSTOM_ZONES_ORDER_BYS)
        queryset = queryset.prefetch_related("geo_zones")
        queryset = queryset.select_related("geo_custom_zone_category")

        return queryset

    @action(methods=["get"], detail=False)
    def get_geometry(self, request):
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

        queryset = self.get_queryset()

        if geometry_serializer.data.get("uuids"):
            try:
                queryset = queryset.filter(
                    uuid__in=geometry_serializer.data["uuids"].split(",")
                )
            except Exception:
                pass

        queryset = queryset.filter(geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE)
        queryset = queryset.filter(geometry__intersects=polygon_requested)
        queryset = queryset.values(
            "uuid",
            "name",
            "color",
            "geo_custom_zone_status",
        )
        queryset = queryset.annotate(
            geometry=Intersection("geometry", polygon_requested)
        )

        serializer = GeoCustomZoneGeoFeatureSerializer(queryset.all(), many=True)

        return Response(serializer.data)
