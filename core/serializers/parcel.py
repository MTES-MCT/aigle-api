import json
from core.models.parcel import Parcel
from core.permissions.tile_set import TileSetPermission
from core.serializers import UuidTimestampedModelSerializerMixin
from core.serializers.detection import DetectionWithTileSerializer
from core.serializers.geo_commune import GeoCommuneSerializer
from core.serializers.detection_object import DetectionObjectMinimalSerializer

from django.contrib.gis.geos import GEOSGeometry
from rest_framework import serializers

from core.serializers.tile_set import TileSetMinimalSerializer
from core.serializers.utils.custom_zones import reconciliate_custom_zones_with_sub


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
    class Meta(DetectionObjectMinimalSerializer.Meta):
        fields = DetectionObjectMinimalSerializer.Meta.fields + [
            "detections",
        ]

    detections = DetectionWithTileSerializer(many=True, read_only=True)


class ParcelDetailSerializer(ParcelSerializer):
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
    detection_objects = ParcelDetectionObjectSerializer(many=True)
    custom_geo_zones = serializers.SerializerMethodField()
    commune_envelope = serializers.SerializerMethodField()
    detections_updated_at = serializers.SerializerMethodField()
    tile_set_previews = serializers.SerializerMethodField()

    def get_commune_envelope(self, obj: Parcel):
        return json.loads(GEOSGeometry(obj.commune.geometry.envelope).geojson)

    def get_custom_geo_zones(self, obj: Parcel):
        # we get the geozones associated to the parcel's detections
        geo_custom_zones_set = set()

        for detection_obj in obj.detection_objects.all():
            geo_custom_zones_set.update(detection_obj.geo_custom_zones.all())

        sub_custom_zones_set = set()

        for detection_obj in obj.detection_objects.all():
            sub_custom_zones_set.update(detection_obj.geo_sub_custom_zones.all())

        return reconciliate_custom_zones_with_sub(
            custom_zones=list(geo_custom_zones_set),
            sub_custom_zones=list(sub_custom_zones_set),
        )

    def get_detections_updated_at(self, obj: Parcel):
        updated_at_values = []

        for detection_object in obj.detection_objects.all():
            for detection in detection_object.detections.all():
                if detection.detection_data.updated_at:
                    updated_at_values.append(detection.detection_data.updated_at)

        return min(updated_at_values) if updated_at_values else None

    def get_tile_set_previews(self, obj: Parcel):
        user = self.context["request"].user
        tile_set_previews = TileSetPermission(user=user).get_previews(
            filter_tile_set_intersects_geometry=obj.geometry,
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
