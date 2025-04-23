from common.views.base import BaseViewSetMixin

from rest_framework.response import Response
from rest_framework import serializers
from django.contrib.gis.geos import Point
from core.contants.geo import SRID
from core.models.detection_object import DetectionObject
from core.serializers.detection_object import (
    DetectionObjectDetailSerializer,
    DetectionObjectHistorySerializer,
    DetectionObjectInputSerializer,
    DetectionObjectSerializer,
)
from rest_framework_gis.fields import GeometryField
from rest_framework.decorators import action
from django.db.models import F

from core.utils.filters import UuidInFilter
from core.views.utils.save_user_position import save_user_position
from django_filters import FilterSet


class GetFromCoordinatesParamsSerializer(serializers.Serializer):
    lat = serializers.FloatField(required=True, allow_null=False)
    lng = serializers.FloatField(required=True, allow_null=False)
    tileSetUuid = serializers.UUIDField(required=True, allow_null=False)


class GetFromCoordinatesOutputSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(required=True, allow_null=False)
    geometry = GeometryField()
    object_type_uuid = serializers.UUIDField(required=True, allow_null=False)
    object_type_color = serializers.CharField(required=True, allow_null=False)


class DetectionObjectFilter(FilterSet):
    uuids = UuidInFilter(method="filter_uuids")
    detectionUuids = UuidInFilter(method="filter_detection_uuids")

    class Meta:
        model = DetectionObject
        fields = ["uuids"]

    def filter_uuids(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(uuid__in=value)

    def filter_detection_uuids(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(detections__uuid__in=value)


class DetectionObjectViewSet(BaseViewSetMixin[DetectionObject]):
    filterset_class = DetectionObjectFilter

    def get_serializer_class(self):
        detail = bool(self.request.query_params.get("detail"))

        if self.action == "retrieve" or detail:
            return DetectionObjectDetailSerializer

        if self.action in ["partial_update", "update"]:
            return DetectionObjectInputSerializer

        if self.action == "history":
            return DetectionObjectHistorySerializer

        return DetectionObjectSerializer

    def get_queryset(self):
        queryset = DetectionObject.objects.order_by("-detections__tile_set__date")
        queryset = queryset.select_related(
            "object_type", "parcel", "parcel__commune"
        ).prefetch_related(
            "detections",
            "detections__tile",
            "detections__tile_set",
            "detections__detection_data",
            "detections__detection_data__user_last_update",
            "detections__detection_data__user_last_update__user_user_groups",
            "detections__detection_data__user_last_update__user_user_groups__user_group",
        )
        queryset = queryset.defer("detections__tile__geometry")
        queryset = queryset.defer("parcel__commune__geometry")
        queryset = queryset.defer("parcel__geometry")

        if self.action == "retrieve":
            queryset = queryset.prefetch_related("geo_custom_zones")
            queryset = queryset.defer("geo_custom_zones__geometry")

        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        try:
            last_position = instance.detections.all()[0].geometry.centroid
            save_user_position(user=request.user, last_position=last_position)
        except Exception:
            pass

        return Response(serializer.data)

    @action(methods=["get"], detail=False, url_path="from-coordinates")
    def get_from_coordinates(self, request):
        params_serializer = GetFromCoordinatesParamsSerializer(data=request.GET)
        params_serializer.is_valid(raise_exception=True)

        point_requested = Point(
            x=params_serializer.data["lng"], y=params_serializer.data["lat"], srid=SRID
        )

        queryset = DetectionObject.objects.filter(
            detections__geometry__intersects=point_requested,
            detections__tile_set__uuid=params_serializer.data["tileSetUuid"],
        )
        queryset = queryset.order_by("-detections__score")
        queryset = queryset.annotate(
            geometry=F("detections__geometry"),
            object_type_uuid=F("object_type__uuid"),
            object_type_color=F("object_type__color"),
        ).values("uuid", "geometry", "object_type_uuid", "object_type_color")
        detection_object = queryset.first()

        if detection_object:
            output_serializer = GetFromCoordinatesOutputSerializer(detection_object)
            output_data = output_serializer.data
        else:
            output_data = None

        return Response(output_data)

    @action(methods=["get"], detail=True)
    def history(self, request, uuid):
        queryset = self.get_queryset()
        detection_object = (
            queryset.prefetch_related("detections").filter(uuid=uuid).first()
        )
        SerializerClass = self.get_serializer_class()
        serializer = SerializerClass(
            detection_object, context={"request": self.request}
        )
        return Response(serializer.data)
