from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from core.models.detection import Detection
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.serializers import UuidTimestampedModelSerializerMixin
from core.serializers.detection_data import (
    DetectionDataInputSerializer,
    DetectionDataSerializer,
)
from core.serializers.geo_custom_zone import GeoCustomZoneSerializer
from core.serializers.object_type import ObjectTypeSerializer
from core.serializers.tile import TileMinimalSerializer, TileSerializer
from core.serializers.tile_set import TileSetMinimalSerializer
from core.services.detection import DetectionService


class DetectionMinimalSerializer(
    UuidTimestampedModelSerializerMixin, GeoFeatureModelSerializer
):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = Detection
        geo_field = "geometry"
        fields = [
            "uuid",
            "object_type_uuid",
            "object_type_color",
            "detection_control_status",
            "detection_validation_status",
            "detection_prescription_status",
            "detection_object_uuid",
            "tile_set_type",
        ]

    object_type_uuid = serializers.CharField(source="detection_object.object_type.uuid")
    object_type_color = serializers.CharField(
        source="detection_object.object_type.color"
    )
    detection_control_status = serializers.ChoiceField(
        source="detection_data.detection_control_status",
        choices=DetectionControlStatus.choices,
    )
    detection_validation_status = serializers.ChoiceField(
        source="detection_data.detection_validation_status",
        choices=DetectionValidationStatus.choices,
    )
    detection_prescription_status = serializers.ChoiceField(
        source="detection_data.detection_prescription_status",
        choices=DetectionPrescriptionStatus.choices,
    )
    detection_object_uuid = serializers.CharField(source="detection_object.uuid")
    tile_set_type = serializers.CharField(source="tile_set.tile_set_type")


class DetectionSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = Detection
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "geometry",
            "score",
            "detection_source",
            "detection_data",
        ]

    detection_data = DetectionDataSerializer(read_only=True)


class DetectionWithTileMinimalSerializer(DetectionSerializer):
    class Meta(DetectionSerializer.Meta):
        fields = DetectionSerializer.Meta.fields + [
            "tile",
        ]

    tile = TileMinimalSerializer(read_only=True)


class DetectionWithTileSerializer(DetectionWithTileMinimalSerializer):
    class Meta(DetectionWithTileMinimalSerializer.Meta):
        fields = DetectionWithTileMinimalSerializer.Meta.fields + [
            "tile_set",
        ]

    tile = TileSerializer(read_only=True)
    tile_set = TileSetMinimalSerializer(read_only=True)


class DetectionDetailSerializer(DetectionWithTileSerializer):
    from core.serializers.detection_object import DetectionObjectSerializer

    class Meta(DetectionWithTileSerializer.Meta):
        fields = DetectionWithTileSerializer.Meta.fields + [
            "detection_object",
        ]

    detection_object = DetectionObjectSerializer(read_only=True)


class DetectionMultipleInputSerializer(serializers.Serializer):
    uuids = serializers.ListField(child=serializers.UUIDField(), required=True)
    object_type_uuid = serializers.UUIDField(required=False)
    detection_control_status = serializers.ChoiceField(
        required=False,
        choices=DetectionControlStatus.choices,
    )
    detection_validation_status = serializers.ChoiceField(
        required=False,
        choices=DetectionValidationStatus.choices,
    )

    def validate(self, data):
        if (
            not data.get("object_type_uuid")
            and not data.get("detection_control_status")
            and not data.get("detection_validation_status")
        ):
            raise serializers.ValidationError(
                "Vous devez spécifier au moins un de ces champs : object_type_uuid, detection_control_status, detection_validation_status"
            )

        return data


class DetectionInputSerializer(DetectionSerializer):
    from core.serializers.detection_object import DetectionObjectInputSerializer

    class Meta(DetectionSerializer.Meta):
        fields = [
            "geometry",
            "detection_data",
            "detection_object",
            "detection_object_uuid",
            "tile_set_uuid",
        ]

    detection_object = DetectionObjectInputSerializer(required=False)
    detection_data = DetectionDataInputSerializer(required=False)
    tile_set_uuid = serializers.UUIDField(write_only=True)
    detection_object_uuid = serializers.UUIDField(write_only=True, required=False)

    def create(self, validated_data):
        user = self.context["request"].user

        detection_object_uuid = validated_data.pop("detection_object_uuid", None)
        tile_set_uuid = validated_data.pop("tile_set_uuid")
        detection_object_data = validated_data.pop("detection_object", None)
        detection_data_data = validated_data.pop("detection_data", None)

        try:
            return DetectionService.create_detection(
                geometry=validated_data["geometry"],
                user=user,
                tile_set_uuid=str(tile_set_uuid),
                detection_object_uuid=str(detection_object_uuid)
                if detection_object_uuid
                else None,
                detection_object_data=detection_object_data,
                detection_data_data=detection_data_data,
            )
        except ValueError as e:
            raise serializers.ValidationError(str(e))


class DetectionUpdateSerializer(DetectionSerializer):
    class Meta(DetectionSerializer.Meta):
        fields = ["object_type_uuid"]

    object_type_uuid = serializers.UUIDField(write_only=True)

    def update(self, instance: Detection, validated_data):
        user = self.context["request"].user
        object_type_uuid = validated_data.get("object_type_uuid")

        if object_type_uuid:
            try:
                return DetectionService.update_detection_object_type(
                    detection=instance,
                    object_type_uuid=str(object_type_uuid),
                    user=user,
                )
            except ValueError as e:
                raise serializers.ValidationError(str(e))

        return instance


class DetectionListItemSerializer(serializers.ModelSerializer):
    from core.serializers.parcel import ParcelMinimalSerializer

    class Meta:
        model = Detection
        fields = [
            "uuid",
            "id",
            "detection_object_id",
            "detection_object_uuid",
            "address",
            "detection_source",
            "score",
            "parcel",
            "geo_custom_zones",
            "object_type",
            "detection_control_status",
            "detection_validation_status",
            "detection_prescription_status",
            "tile_sets",
            "commune_name",
            "commune_iso_code",
        ]

    detection_object_id = serializers.IntegerField(
        source="detection_object.id", read_only=True
    )
    detection_object_uuid = serializers.UUIDField(
        source="detection_object.uuid", read_only=True
    )
    address = serializers.CharField(source="detection_object.address", read_only=True)
    parcel = ParcelMinimalSerializer(read_only=True, source="detection_object.parcel")
    geo_custom_zones = GeoCustomZoneSerializer(
        many=True, read_only=True, source="detection_object.geo_custom_zones"
    )
    object_type = ObjectTypeSerializer(
        read_only=True, source="detection_object.object_type"
    )
    detection_control_status = serializers.ChoiceField(
        source="detection_data.detection_control_status",
        choices=DetectionControlStatus.choices,
    )
    detection_validation_status = serializers.ChoiceField(
        source="detection_data.detection_validation_status",
        choices=DetectionValidationStatus.choices,
    )
    detection_prescription_status = serializers.ChoiceField(
        source="detection_data.detection_prescription_status",
        choices=DetectionPrescriptionStatus.choices,
    )
    tile_sets = TileSetMinimalSerializer(source="detection_object.tile_sets", many=True)

    commune_name = serializers.CharField(
        source="detection_object.commune.name", read_only=True
    )
    commune_iso_code = serializers.CharField(
        source="detection_object.commune.iso_code", read_only=True
    )
