from core.models.detection_data import (
    DetectionData,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.models.detection import Detection
from core.models.tile_set import TileSet, TileSetType
from core.models.user_group import UserGroupRight
from core.serializers import UuidTimestampedModelSerializerMixin
from django.contrib.gis.db.models.functions import Centroid
from dateutil.relativedelta import relativedelta
from simple_history.utils import bulk_create_with_history
from rest_framework import serializers

from core.utils.data_permissions import get_user_group_rights


class DetectionDataSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = DetectionData
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "detection_control_status",
            "detection_validation_status",
            "detection_prescription_status",
            "user_last_update_uuid",
        ]

    user_last_update_uuid = serializers.UUIDField(
        source="user_last_update.uuid", read_only=True
    )


class DetectionDataInputSerializer(DetectionDataSerializer):
    class Meta(DetectionDataSerializer.Meta):
        fields = [
            "detection_control_status",
            "detection_validation_status",
            "detection_prescription_status",
        ]

    def update(self, instance: DetectionData, validated_data):
        user = self.context["request"].user
        centroid = Centroid(instance.detection.geometry)

        get_user_group_rights(
            user=user, points=[centroid], raise_if_has_no_right=UserGroupRight.WRITE
        )

        # if object get prescribed, we add data for the prescribed years
        if (
            "detection_prescription_status" in validated_data
            and instance.detection_prescription_status
            != validated_data["detection_prescription_status"]
            and validated_data["detection_prescription_status"]
            == DetectionPrescriptionStatus.PRESCRIBED
        ):
            prescription_duration_years = instance.detection.detection_object.object_type.prescription_duration_years
            date_max = instance.detection.tile_set.date
            date_min = date_max - relativedelta(years=prescription_duration_years)
            existing_tile_set_ids = []

            for (
                existing_detection
            ) in instance.detection.detection_object.detections.filter(
                tile_set__date__gte=date_min,
                tile_set__date__lt=date_max,
            ).all():
                existing_tile_set_ids.append(existing_detection.tile_set.id)

            tile_sets = TileSet.objects.filter(
                date__gte=date_min,
                date__lt=date_max,
            ).exclude(
                tile_set_type=TileSetType.INDICATIVE, id__in=existing_tile_set_ids
            )

            if tile_sets:
                detections_to_insert = []

                for tile_set in tile_sets:
                    detection_data = DetectionData(
                        detection_control_status=instance.detection.detection_data.detection_control_status,
                        detection_validation_status=instance.detection.detection_data.detection_validation_status,
                        detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED,
                        user_last_update=user,
                    )
                    detection_data.save()
                    detection = Detection(
                        geometry=instance.detection.geometry,
                        score=1,
                        detection_source=instance.detection.detection_source,
                        detection_object=instance.detection.detection_object,
                        detection_data=detection_data,
                        auto_prescribed=False,
                        tile=instance.detection.tile,
                        tile_set=tile_set,
                    )
                    detections_to_insert.append(detection)

                bulk_create_with_history(detections_to_insert, Detection)

        for key, value in validated_data.items():
            setattr(instance, key, value)

        if (
            instance.detection_validation_status
            == DetectionValidationStatus.DETECTED_NOT_VERIFIED
        ):
            instance.detection_validation_status = DetectionValidationStatus.SUSPECT

        instance.user_last_update = user
        instance.save()

        return instance
