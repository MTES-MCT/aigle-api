from rest_framework.response import Response
from common.views.base import BaseViewSetMixin

from rest_framework import serializers
from core.models.geo_custom_zone import GeoCustomZone
from core.serializers.geo_custom_zone import (
    GeoCustomZoneGeoFeatureSerializer,
    GeoCustomZoneInputSerializer,
    GeoCustomZoneSerializer,
    GeoCustomZoneWithCollectivitiesSerializer,
)
from django_filters import FilterSet, CharFilter

from rest_framework.decorators import action

from core.utils.permissions import AdminRolePermission


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
        from core.services.geo_custom_zone import GeoCustomZoneService

        search_query = self.request.GET.get("q")
        return GeoCustomZoneService.get_filtered_queryset(
            user=self.request.user, search_query=search_query
        )

    @action(methods=["get"], detail=False)
    def get_geometry(self, request):
        from core.services.geo_custom_zone import GeoCustomZoneService

        geometry_serializer = GeometrySerializer(data=request.GET)
        geometry_serializer.is_valid(raise_exception=True)

        # Parse UUIDs if provided
        zone_uuids = None
        if geometry_serializer.data.get("uuids"):
            try:
                zone_uuids = geometry_serializer.data["uuids"].split(",")
            except AttributeError:
                # uuids is not a string
                pass

        # Use service to get zones by geometry
        zones_data = GeoCustomZoneService.get_zones_by_geometry(
            ne_lat=geometry_serializer.data["neLat"],
            ne_lng=geometry_serializer.data["neLng"],
            sw_lat=geometry_serializer.data["swLat"],
            sw_lng=geometry_serializer.data["swLng"],
            zone_uuids=zone_uuids,
        )

        serializer = GeoCustomZoneGeoFeatureSerializer(zones_data, many=True)
        return Response(serializer.data)
