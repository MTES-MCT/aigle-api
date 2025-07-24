from common.constants.models import DEFAULT_MAX_LENGTH
from core.models.detection_object import DetectionObject
from core.serializers import UuidTimestampedModelSerializerMixin
from core.serializers.object_type import ObjectTypeSerializer
from core.serializers.tile_set import TileSetMinimalSerializer
from core.services.detection_object import DetectionObjectService
from rest_framework import serializers


class DetectionObjectMinimalSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = DetectionObject
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "id",
            "address",
            "comment",
            "object_type",
        ]

    comment = serializers.CharField(
        max_length=DEFAULT_MAX_LENGTH, allow_null=True, allow_blank=True, required=False
    )
    object_type = ObjectTypeSerializer(read_only=True)


class DetectionObjectSerializer(DetectionObjectMinimalSerializer):
    from core.serializers.parcel import ParcelWithCommuneSerializer

    class Meta(DetectionObjectMinimalSerializer.Meta):
        fields = DetectionObjectMinimalSerializer.Meta.fields + [
            "parcel",
        ]

    parcel = ParcelWithCommuneSerializer(read_only=True)


class DetectionHistorySerializer(serializers.Serializer):
    from core.serializers.detection import DetectionWithTileMinimalSerializer

    tile_set = TileSetMinimalSerializer(read_only=True)
    detection = DetectionWithTileMinimalSerializer(read_only=True, required=False)


class DetectionObjectHistorySerializer(DetectionObjectSerializer):
    class Meta(DetectionObjectSerializer.Meta):
        fields = DetectionObjectSerializer.Meta.fields + [
            "id",
            "detections",
        ]

    detections = serializers.SerializerMethodField()

    def get_detections(self, obj: DetectionObject):
        user = self.context["request"].user
        detection_history_data = DetectionObjectService.get_detection_history_data(
            detection_object=obj, user=user
        )

        from core.serializers.detection import DetectionWithTileMinimalSerializer

        detection_history = []
        for history_item in detection_history_data:
            tile_set = history_item["tile_set"]
            detection = history_item["detection"]

            history = DetectionHistorySerializer(
                data={
                    "tile_set": TileSetMinimalSerializer(tile_set).data,
                    "detection": (
                        DetectionWithTileMinimalSerializer(detection).data
                        if detection
                        else None
                    ),
                }
            )
            detection_history.append(history.initial_data)

        return detection_history


class DetectionObjectTileSetPreviewSerializer(serializers.Serializer):
    preview = serializers.BooleanField()
    tile_set = TileSetMinimalSerializer()


class DetectionObjectDetailSerializer(DetectionObjectSerializer):
    from core.serializers.parcel import ParcelSerializer

    class Meta(DetectionObjectSerializer.Meta):
        fields = DetectionObjectSerializer.Meta.fields + [
            "id",
            "detections",
            "tile_sets",
            "user_group_rights",
            "geo_custom_zones",
            "user_group_last_update",
        ]

    detections = serializers.SerializerMethodField()
    tile_sets = serializers.SerializerMethodField()
    user_group_rights = serializers.SerializerMethodField()
    parcel = ParcelSerializer(read_only=True)
    user_group_last_update = serializers.SerializerMethodField(read_only=True)
    geo_custom_zones = serializers.SerializerMethodField()

    def get_geo_custom_zones(self, obj: DetectionObject):
        return DetectionObjectService.get_custom_zones_reconciled(detection_object=obj)

    def get_user_group_last_update(self, obj: DetectionObject):
        return DetectionObjectService.get_user_group_last_update(detection_object=obj)

    def get_detections(self, obj: DetectionObject):
        user = self.context["request"].user

        if self.context.get("tile_set_previews"):
            tile_set_previews = self.context["tile_set_previews"]
        else:
            tile_set_previews = DetectionObjectService.get_tile_set_previews_data(
                detection_object=obj, user=user
            )
            self.context["tile_set_previews"] = tile_set_previews

        detections = DetectionObjectService.get_filtered_detections_queryset(
            detection_object=obj, user=user, tile_set_previews=tile_set_previews
        )

        from core.serializers.detection import DetectionWithTileSerializer

        detections_serialized = DetectionWithTileSerializer(detections, many=True)
        return detections_serialized.data

    def get_tile_sets(self, obj: DetectionObject):
        user = self.context["request"].user

        if self.context.get("tile_set_previews"):
            tile_set_previews = self.context["tile_set_previews"]
        else:
            tile_set_previews = DetectionObjectService.get_tile_set_previews_data(
                detection_object=obj, user=user
            )
            self.context["tile_set_previews"] = tile_set_previews

        if not tile_set_previews:
            return []

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

    def get_user_group_rights(self, obj: DetectionObject):
        user = self.context["request"].user

        return DetectionObjectService.get_user_group_rights(
            detection_object=obj, user=user
        )


class DetectionObjectInputSerializer(DetectionObjectSerializer):
    class Meta(DetectionObjectSerializer.Meta):
        fields = ["address", "object_type_uuid", "comment"]

    object_type_uuid = serializers.UUIDField(write_only=True)

    def update(self, instance: DetectionObject, validated_data):
        user = self.context["request"].user
        object_type_uuid = validated_data.pop("object_type_uuid", None)

        try:
            return DetectionObjectService.update_detection_object_comprehensive(
                detection_object=instance,
                user=user,
                address=validated_data.get("address"),
                comment=validated_data.get("comment"),
                object_type_uuid=str(object_type_uuid) if object_type_uuid else None,
            )
        except ValueError as e:
            raise serializers.ValidationError(str(e))
