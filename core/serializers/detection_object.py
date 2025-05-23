from common.constants.models import DEFAULT_MAX_LENGTH
from core.models.detection import Detection
from core.models.detection_data import DetectionValidationStatus
from core.models.detection_object import DetectionObject
from core.models.object_type import ObjectType
from core.models.tile_set import TileSetStatus, TileSetType
from core.permissions.tile_set import TileSetPermission
from core.permissions.user import UserPermission
from core.serializers import UuidTimestampedModelSerializerMixin
from django.contrib.gis.db.models.functions import Centroid

from core.serializers.detection import (
    DetectionWithTileMinimalSerializer,
    DetectionWithTileSerializer,
)
from core.serializers.object_type import ObjectTypeSerializer
from rest_framework import serializers

from core.serializers.tile_set import TileSetMinimalSerializer
from core.serializers.user_group import UserGroupSerializer
from core.serializers.utils.custom_zones import reconciliate_custom_zones_with_sub
from core.utils.data_permissions import get_user_group_rights
from core.utils.prescription import compute_prescription


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
        detections = obj.detections.order_by("-tile_set__date").all()
        tile_sets = TileSetPermission(user=user).list_(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            order_bys=["-date"],
            filter_tile_set_intersects_geometry=detections[0].geometry,
        )

        if not tile_sets:
            return []

        detection_history = []
        tile_set_id_detection_map = {
            detection.tile_set.id: detection for detection in detections
        }

        for tile_set in list(sorted(tile_sets, key=lambda t: t.date)):
            detection = tile_set_id_detection_map.get(tile_set.id, None)

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
        return reconciliate_custom_zones_with_sub(
            custom_zones=list(obj.geo_custom_zones.all()),
            sub_custom_zones=list(obj.geo_sub_custom_zones.all()),
        )

    def get_user_group_last_update(self, obj: DetectionObject):
        most_recent_detection_update = get_most_recent_detection(detection_object=obj)
        detection_data = most_recent_detection_update.detection_data

        if not detection_data.user_last_update:
            return None

        user_user_group = (
            detection_data.user_last_update.user_user_groups.order_by("created_at")
            .all()
            .first()
        )

        if not user_user_group:
            return None

        return UserGroupSerializer(user_user_group.user_group).data

    def get_detections(self, obj: DetectionObject):
        user = self.context["request"].user

        if self.context.get("tile_set_previews"):
            tile_set_previews = self.context["tile_set_previews"]
        else:
            tile_set_previews = TileSetPermission(user=user).get_previews(
                filter_tile_set_intersects_geometry=obj.detections.all()[0].geometry,
            )
            self.context["tile_set_previews"] = tile_set_previews

        detections = obj.detections.order_by("-tile_set__date").filter(
            tile_set__id__in=[tpreview["tile_set"].id for tpreview in tile_set_previews]
        )

        detections_serialized = DetectionWithTileSerializer(detections, many=True)
        return detections_serialized.data

    def get_tile_sets(self, obj: DetectionObject):
        user = self.context["request"].user

        if self.context.get("tile_set_previews"):
            tile_set_previews = self.context["tile_set_previews"]
        else:
            tile_set_previews = TileSetPermission(user=user).get_previews(
                filter_tile_set_intersects_geometry=obj.detections.all()[0].geometry,
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
        point = Centroid(obj.detections.order_by("-tile_set__date").first().geometry)

        return get_user_group_rights(user=user, points=[point])


class DetectionObjectInputSerializer(DetectionObjectSerializer):
    class Meta(DetectionObjectSerializer.Meta):
        fields = ["address", "object_type_uuid", "comment"]

    object_type_uuid = serializers.UUIDField(write_only=True)

    def update(self, instance: DetectionObject, validated_data):
        object_type = None
        object_type_uuid = validated_data.pop("object_type_uuid", None)

        if object_type_uuid and instance.object_type.uuid != object_type_uuid:
            object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()

            if not object_type:
                raise serializers.ValidationError(
                    f"Object type with following uuid not found: {
                        object_type_uuid}"
                )

        user = self.context["request"].user

        latest_detection = get_most_recent_detection(detection_object=instance)

        UserPermission(user=user).can_edit(
            geometry=latest_detection.geometry, raise_exception=True
        )

        for key, value in validated_data.items():
            setattr(instance, key, value)

        instance.save()

        if object_type:
            instance.object_type = object_type
            compute_prescription(instance)
            instance.save()

            # change last detection validation status to suspect if was not verified
            if (
                latest_detection.detection_data.detection_validation_status
                == DetectionValidationStatus.DETECTED_NOT_VERIFIED
            ):
                latest_detection.detection_data.detection_validation_status = (
                    DetectionValidationStatus.SUSPECT
                )
                latest_detection.detection_data.save()

        return instance


# utils


def get_most_recent_detection(detection_object: DetectionObject) -> Detection:
    return (
        detection_object.detections.exclude(
            tile_set__tile_set_status=TileSetStatus.DEACTIVATED
        )
        .filter(
            tile_set__tile_set_type__in=[TileSetType.BACKGROUND, TileSetType.PARTIAL]
        )
        .select_related("detection_data")
        .order_by("-tile_set__date")
        .first()
    )
