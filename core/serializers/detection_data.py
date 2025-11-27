from core.models.detection_authorization import DetectionAuthorization
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
    DetectionValidationStatusChangeReason,
)
from core.models.detection import Detection
from core.models.tile_set import TileSet, TileSetType
from core.permissions.user import UserPermission
from core.serializers import UuidTimestampedModelSerializerMixin
from dateutil.relativedelta import relativedelta
from simple_history.utils import bulk_create_with_history
from rest_framework import serializers


class DetectionDataSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = DetectionData
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "detection_control_status",
            "detection_validation_status",
            "detection_prescription_status",
            "user_last_update_uuid",
            "official_report_date",
            "detection_validation_status_change_reason",
            "legitimate_date",
            "authorization_ids",
        ]

    legitimate_date = serializers.SerializerMethodField()

    def get_legitimate_date(self, obj: DetectionData):
        detection_authorizations = obj.detection_authorizations.all()

        if not detection_authorizations:
            return None

        return min(auth.authorization_date for auth in detection_authorizations)

    authorization_ids = serializers.SerializerMethodField()

    def get_authorization_ids(self, obj: DetectionData):
        detection_authorizations = obj.detection_authorizations.all()
        authorization_ids = [
            auth.authorization_id
            for auth in detection_authorizations
            if auth.authorization_id
        ]

        if not authorization_ids:
            return None

        return authorization_ids

    user_last_update_uuid = serializers.UUIDField(
        source="user_last_update.uuid", read_only=True
    )


class DetectionDataInputSerializer(DetectionDataSerializer):
    class Meta(DetectionDataSerializer.Meta):
        fields = [
            "detection_control_status",
            "detection_validation_status",
            "detection_prescription_status",
            "official_report_date",
            "legitimate_date",
        ]

    legitimate_date = serializers.DateField(write_only=True)

    def update(self, instance: DetectionData, validated_data):
        user = self.context["request"].user

        UserPermission(user=user).can_edit(
            geometry=instance.detection.geometry, raise_exception=True
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

        # if object get unpresribed, we remove detections for the previous years
        if (
            "detection_prescription_status" in validated_data
            and instance.detection_prescription_status
            != validated_data["detection_prescription_status"]
            and validated_data["detection_prescription_status"]
            == DetectionPrescriptionStatus.NOT_PRESCRIBED
        ):
            prescription_duration_years = instance.detection.detection_object.object_type.prescription_duration_years
            date_max = instance.detection.tile_set.date
            date_min = date_max - relativedelta(years=prescription_duration_years)

            instance.detection.detection_object.detections.filter(
                tile_set__date__gte=date_min,
                tile_set__date__lt=date_max,
            ).delete()

        detection_control_status = (
            validated_data.get("detection_control_status")
            or instance.detection_control_status
        )

        # allow update official_report_date only if detection_control_status isOFFICIAL_REPORT_DRAWN_UP
        if detection_control_status != DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP:
            validated_data.pop("official_report_date", None)

        # do not allow to change detection_validation_status or legitimate_date if has been changed by SITADEL
        if (
            instance.detection_validation_status_change_reason
            == DetectionValidationStatusChangeReason.SITADEL
        ):
            validated_data.pop("detection_validation_status", None)
            validated_data.pop("legitimate_date", None)

        detection_validation_status = (
            validated_data.get("detection_validation_status")
            or instance.detection_validation_status
        )

        # allow update official_report_date only if detection_validation_status is LEGITIMATE
        if detection_validation_status != DetectionValidationStatus.LEGITIMATE:
            validated_data.pop("legitimate_date", None)

        if validated_data.get("legitimate_date"):
            existing_auth = instance.detection_authorizations.filter(
                authorization_id=None
            ).first()
            if not existing_auth:
                detection_authorization = DetectionAuthorization(
                    detection_data=instance,
                )
            if existing_auth:
                detection_authorization = existing_auth

            detection_authorization.authorization_date = validated_data.pop(
                "legitimate_date"
            )
            detection_authorization.save()

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
