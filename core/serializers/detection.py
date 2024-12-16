from core.models.detection import Detection
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.models.detection_object import DetectionObject
from core.models.geo_custom_zone import GeoCustomZone
from core.models.object_type import ObjectType
from core.models.parcel import Parcel
from core.models.tile import TILE_DEFAULT_ZOOM, Tile
from core.models.tile_set import TileSet
from core.models.user_group import UserGroupRight
from core.serializers import UuidTimestampedModelSerializerMixin
from core.serializers.detection_data import DetectionDataInputSerializer

from rest_framework_gis.serializers import GeoFeatureModelSerializer
from rest_framework import serializers

from core.serializers.tile import TileSerializer
from core.serializers.tile_set import TileSetMinimalSerializer
from django.contrib.gis.db.models.functions import Centroid

from core.utils.data_permissions import get_user_group_rights
from core.utils.detection import get_linked_detections
from core.utils.prescription import compute_prescription


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
    from core.serializers.detection_data import DetectionDataSerializer

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

    tile = TileSerializer(read_only=True)


class DetectionWithTileSerializer(DetectionWithTileMinimalSerializer):
    class Meta(DetectionWithTileMinimalSerializer.Meta):
        fields = DetectionWithTileMinimalSerializer.Meta.fields + [
            "tile_set",
        ]

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
        centroid = Centroid(validated_data["geometry"])

        get_user_group_rights(
            user=user, points=[centroid], raise_if_has_no_right=UserGroupRight.WRITE
        )

        # create or retrieve detection object

        detection_object_uuid = validated_data.pop("detection_object_uuid", None)

        tile_set_uuid = validated_data.pop("tile_set_uuid")
        tile_set = None

        if tile_set_uuid:
            tile_set = TileSet.objects.filter(
                uuid=tile_set_uuid,
            ).first()

            if not tile_set:
                raise serializers.ValidationError(
                    f"Tile set with following uuid not found: {tile_set_uuid}"
                )

        tile = Tile.objects.filter(
            geometry__contains=centroid, z=TILE_DEFAULT_ZOOM
        ).first()

        if not tile:
            raise serializers.ValidationError("Tile not found for specified geometry")

        if not detection_object_uuid:
            detection_object_data = validated_data.pop("detection_object", None)

            if not detection_object_data:
                raise serializers.ValidationError(
                    "detectionObjectUuid or detectionObject must be specified"
                )

            object_type_uuid = detection_object_data.pop("object_type_uuid")
            object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()

            if not object_type:
                raise serializers.ValidationError(
                    f"Object type with following uuid not found: {
                        object_type_uuid}"
                )

            # search for existing detection object

            linked_detections = get_linked_detections(
                detection_geometry=validated_data["geometry"],
                object_type_id=object_type.id,
                exclude_tile_set_ids=[tile_set.id],
            )

            if linked_detections:
                detection_object = linked_detections[0].detection_object
            else:
                # get tile_set and tile

                detection_object = DetectionObject(**detection_object_data)
                detection_object.object_type = object_type

                parcel = Parcel.objects.filter(geometry__contains=centroid).first()
                detection_object.parcel = parcel

                detection_object.save()

                # update geo_custom_zones

                geo_custom_zones = GeoCustomZone.objects.filter(
                    geometry__intersects=validated_data["geometry"]
                ).all()

                detection_object.geo_custom_zones.add(*geo_custom_zones)

                detection_object.save()

        if detection_object_uuid:
            detection_object = DetectionObject.objects.filter(
                uuid=detection_object_uuid
            ).first()

            if not detection_object:
                raise serializers.ValidationError(
                    f"Detection object with following uuid not found: {
                        detection_object_uuid}"
                )

        # create detection data

        detection_data_data = validated_data.pop("detection_data", None)

        if detection_data_data:
            detection_data = DetectionData(**detection_data_data)
        else:
            # default value
            detection_data = DetectionData(
                detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
                detection_validation_status=DetectionValidationStatus.SUSPECT,
            )

        if (
            detection_data.detection_prescription_status is None
            and detection_object.object_type.prescription_duration_years
        ):
            detection_data.detection_prescription_status = (
                DetectionPrescriptionStatus.NOT_PRESCRIBED
            )

        if (
            detection_data.detection_prescription_status is not None
            and not detection_object.object_type.prescription_duration_years
        ):
            detection_data.detection_prescription_status = None

        detection_data.user_last_update = user
        detection_data.save()

        # create detection

        instance = Detection(**validated_data)

        instance.detection_object = detection_object
        instance.detection_data = detection_data

        if tile_set:
            instance.tile_set = tile_set

        if tile:
            instance.tile = tile

        instance.save()

        # update prescription
        compute_prescription(detection_object)

        return instance


class DetectionUpdateSerializer(DetectionSerializer):
    class Meta(DetectionSerializer.Meta):
        fields = ["object_type_uuid"]

    object_type_uuid = serializers.UUIDField(write_only=True)

    def update(self, instance: Detection, validated_data):
        user = self.context["request"].user
        centroid = Centroid(instance.geometry)

        get_user_group_rights(
            user=user, points=[centroid], raise_if_has_no_right=UserGroupRight.WRITE
        )

        object_type_uuid = validated_data.get("object_type_uuid")

        if object_type_uuid:
            object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()

            if not object_type:
                raise serializers.ValidationError(
                    f"Object type with following uuid not found: {
                        object_type_uuid}"
                )

            instance.detection_object.object_type = object_type

            # update prescription
            compute_prescription(instance.detection_object)

        instance.save()

        return instance
