from common.views.base import BaseViewSetMixin

from rest_framework.response import Response
from rest_framework import serializers
from core.models.detection_object import DetectionObject
from core.models.tile_set import TileSetType
from core.permissions.geo_custom_zone import GeoCustomZonePermission
from core.serializers.detection_object import (
    DetectionObjectDetailSerializer,
    DetectionObjectHistorySerializer,
    DetectionObjectInputSerializer,
    DetectionObjectSerializer,
)
from django.core.exceptions import PermissionDenied
from rest_framework_gis.fields import GeometryField
from rest_framework.decorators import action

from core.utils.filters import UuidInFilter
from core.services.detection_object import DetectionObjectService
from core.services.tile_set import TileSetService
from django_filters import FilterSet


class GetFromCoordinatesParamsSerializer(serializers.Serializer):
    lat = serializers.FloatField(required=True, allow_null=False)
    lng = serializers.FloatField(required=True, allow_null=False)


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

    def filter_uuids(self, queryset, value):
        if not value:
            return queryset

        return queryset.filter(uuid__in=value)

    def filter_detection_uuids(self, queryset, value):
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
            geo_custom_zones_prefetch, geo_custom_zones_category_prefetch = (
                GeoCustomZonePermission(
                    user=self.request.user
                ).get_detection_object_prefetch()
            )

            queryset = queryset.prefetch_related(
                geo_custom_zones_prefetch,
                geo_custom_zones_category_prefetch,
            )
            queryset = queryset.defer(
                "geo_custom_zones__geometry", "geo_sub_custom_zones__geometry"
            )

        return queryset

    def retrieve(self, request, uuid):
        """Retrieve detection object with position saving logic moved to service."""
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        # Business logic moved to service
        try:
            last_position = instance.detections.all()[0].geometry.centroid
            DetectionObjectService.save_user_position(
                user=request.user, x=last_position.x, y=last_position.y
            )
        except (IndexError, AttributeError):
            # No detections or geometry available
            pass

        return Response(serializer.data)

    @action(methods=["get"], detail=False, url_path="from-coordinates")
    def get_from_coordinates(self, request):
        params_serializer = GetFromCoordinatesParamsSerializer(data=request.GET)
        params_serializer.is_valid(raise_exception=True)

        x = params_serializer.data["lng"]
        y = params_serializer.data["lat"]

        # Use service to find tile set
        tile_set = TileSetService.find_tile_set_by_coordinates(
            x=x,
            y=y,
            user=request.user,
            tile_set_types=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
        )

        if not tile_set:
            raise PermissionDenied(
                "Vous n'avez pas les droits pour chercher une détection ici"
            )

        # Use service to find detection objects
        detection_objects = DetectionObjectService.find_detections_by_coordinates(
            x=x,
            y=y,
            user=request.user,
            tile_set_types=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
        )

        if detection_objects:
            # Get the first detection object and prepare response data
            detection_object = detection_objects[0]
            most_recent_detection = detection_object.detections.order_by(
                "-score"
            ).first()

            if most_recent_detection:
                output_data = {
                    "uuid": detection_object.uuid,
                    "geometry": most_recent_detection.geometry,
                    "object_type_uuid": detection_object.object_type.uuid,
                    "object_type_color": detection_object.object_type.color,
                }
                output_serializer = GetFromCoordinatesOutputSerializer(output_data)
                output_data = output_serializer.data
            else:
                output_data = None
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
        serializer = SerializerClass(detection_object, context={"request": request})
        return Response(serializer.data)
