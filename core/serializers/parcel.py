from collections import defaultdict
import json

from django.contrib.gis.geos import GEOSGeometry
from rest_framework import serializers

from core.models.parcel import Parcel
from core.serializers import UuidTimestampedModelSerializerMixin
from core.serializers.detection_object import DetectionObjectMinimalSerializer
from core.serializers.geo_commune import GeoCommuneSerializer
from core.serializers.tile_set import TileSetMinimalSerializer
from core.services.parcel import ParcelService


class ParcelMinimalSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = Parcel
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "id_parcellaire",
            "prefix",
            "section",
            "num_parcel",
        ]


class ParcelWithCommuneSerializer(ParcelMinimalSerializer):
    class Meta(ParcelMinimalSerializer.Meta):
        fields = ParcelMinimalSerializer.Meta.fields + [
            "commune",
        ]

    commune = GeoCommuneSerializer(read_only=True)


class ParcelSerializer(ParcelWithCommuneSerializer):
    class Meta(ParcelWithCommuneSerializer.Meta):
        fields = ParcelWithCommuneSerializer.Meta.fields + [
            "geometry",
        ]


class ParcelDetectionObjectSerializer(DetectionObjectMinimalSerializer):
    from core.serializers.detection import DetectionWithTileSerializer

    class Meta(DetectionObjectMinimalSerializer.Meta):
        fields = DetectionObjectMinimalSerializer.Meta.fields + [
            "detections",
        ]

    detections = DetectionWithTileSerializer(many=True, read_only=True)


class ParcelCustomGeoZoneMixin(serializers.ModelSerializer):
    class Meta:
        fields = [
            "custom_geo_zones",
        ]

    custom_geo_zones = serializers.SerializerMethodField()

    def get_custom_geo_zones(self, obj: Parcel):
        return ParcelService.get_parcel_custom_geo_zones(parcel=obj)


class ParcelDetectionObjectsMixin(serializers.ModelSerializer):
    detection_objects = ParcelDetectionObjectSerializer(many=True)


class ParcelDetailSerializer(
    ParcelSerializer, ParcelCustomGeoZoneMixin, ParcelDetectionObjectsMixin
):
    class Meta(ParcelSerializer.Meta):
        fields = ParcelSerializer.Meta.fields + [
            "detection_objects",
            "custom_geo_zones",
            "commune",
            "commune_envelope",
            "detections_updated_at",
            "tile_set_previews",
        ]

    commune = GeoCommuneSerializer(read_only=True)
    commune_envelope = serializers.SerializerMethodField()
    detections_updated_at = serializers.SerializerMethodField()
    tile_set_previews = serializers.SerializerMethodField()

    def get_commune_envelope(self, obj: Parcel):
        return json.loads(GEOSGeometry(obj.commune.geometry.envelope).geojson)

    def get_detections_updated_at(self, obj: Parcel):
        return ParcelService.get_parcel_detections_updated_at(parcel=obj)

    def get_tile_set_previews(self, obj: Parcel):
        user = self.context["request"].user

        tile_set_previews = ParcelService.get_parcel_tile_set_previews_data(
            parcel=obj, user=user
        )

        from core.serializers.detection_object import (
            DetectionObjectTileSetPreviewSerializer,
        )

        previews_serialized = []

        for tile_set_preview in tile_set_previews:
            preview = DetectionObjectTileSetPreviewSerializer(
                data={
                    "tile_set": TileSetMinimalSerializer(
                        tile_set_preview["tile_set"]
                    ).data,
                    "preview": tile_set_preview["preview"],
                }
            )
            previews_serialized.append(preview.initial_data)

        return previews_serialized


class ParcelListItemDetectionCountByObjectTypeSerializer(serializers.Serializer):
    object_type_name = serializers.CharField(required=True)
    object_type_uuid = serializers.CharField(required=True)
    object_type_color = serializers.CharField(required=True)
    count = serializers.IntegerField(required=True)


class ParcelListItemSerializer(ParcelWithCommuneSerializer):
    class Meta(ParcelWithCommuneSerializer.Meta):
        fields = ParcelWithCommuneSerializer.Meta.fields + [
            "zone_names",
            "detections_count",
            "detections_count_by_object_type",
        ]

    zone_names = serializers.SerializerMethodField()
    detections_count = serializers.SerializerMethodField()
    detections_count_by_object_type = serializers.SerializerMethodField()

    def get_zone_names(self, obj: Parcel):
        return obj.zone_names or []

    def get_detections_count(self, obj: Parcel):
        return obj.detections_count

    def get_detections_count_by_object_type(self, obj: Parcel):
        detections_count_by_object_type_map = defaultdict(int)
        object_types_map = dict()

        # Check if detection_objects has been prefetched with filters
        # If it has, use the prefetched data directly
        if (
            hasattr(obj, "_prefetched_objects_cache")
            and "detection_objects" in obj._prefetched_objects_cache
        ):
            detection_objects = obj._prefetched_objects_cache["detection_objects"]
        else:
            detection_objects = obj.detection_objects.all()

        for detection_object in detection_objects:
            object_type_uuid = detection_object.object_type.uuid

            if object_type_uuid not in object_types_map:
                object_types_map[object_type_uuid] = detection_object.object_type

            detections_count_by_object_type_map[object_type_uuid] += 1

        return ParcelListItemDetectionCountByObjectTypeSerializer(
            [
                {
                    "object_type_name": object_types_map[object_type_uuid].name,
                    "object_type_uuid": object_types_map[object_type_uuid].uuid,
                    "object_type_color": object_types_map[object_type_uuid].color,
                    "count": object_type_count,
                }
                for object_type_uuid, object_type_count in detections_count_by_object_type_map.items()
            ],
            many=True,
        ).data


class ParcelOverviewSerializer(serializers.Serializer):
    not_verified = serializers.IntegerField(
        help_text="Number of parcels that have more than 50% of their detections in DETECTED_NOT_VERIFIED status"
    )
    verified = serializers.IntegerField(
        help_text="Number of parcels that have 50% or more of their detections in SUSPECT, LEGITIMATE, or INVALIDATED status"
    )
    total = serializers.IntegerField(
        help_text="Total number of parcels in the filtered queryset"
    )
