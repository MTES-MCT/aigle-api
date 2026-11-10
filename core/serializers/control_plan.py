from django.utils import timezone
from rest_framework import serializers

from core.constants.control_plan import (
    DEFAULT_SCORE_MIN,
    MAX_PARCELS_COUNT,
    SELECTABLE_VALIDATION_STATUSES,
    ControlPlanRankingCriterion,
)
from core.models.control_plan import (
    ControlPlan,
    ControlPlanParcel,
    ControlPlanStatus,
    ControlPlanWave,
    ControlPlanWaveStatus,
)
from core.serializers import UuidTimestampedModelSerializerMixin
from core.serializers.parcel import ParcelListItemSerializer


def _unique(value, message):
    if len(set(value)) != len(value):
        raise serializers.ValidationError(message)
    return value


class ControlPlanCriteriaSerializer(serializers.Serializer):
    # perimeter inside the group territory; both empty: the whole territory
    communes_uuids = serializers.ListField(child=serializers.UUIDField(), default=list)
    epcis_uuids = serializers.ListField(child=serializers.UUIDField(), default=list)
    object_types_uuids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1
    )
    score_min = serializers.FloatField(
        min_value=0, max_value=1, default=DEFAULT_SCORE_MIN
    )
    validation_statuses = serializers.ListField(
        child=serializers.ChoiceField(choices=SELECTABLE_VALIDATION_STATUSES),
        min_length=1,
        default=lambda: list(SELECTABLE_VALIDATION_STATUSES),
    )
    include_prescribed = serializers.BooleanField(default=False)
    # zone groups by priority, the first one first
    custom_zone_groups = serializers.ListField(
        child=serializers.ListField(child=serializers.UUIDField(), min_length=1),
        min_length=1,
    )
    exclude_authorized_parcels = serializers.BooleanField(default=True)
    exclude_official_report_parcels = serializers.BooleanField(default=True)
    min_objects_count = serializers.IntegerField(min_value=1, default=1)
    # the active ranking criteria, by importance
    ranking_criteria = serializers.ListField(
        child=serializers.ChoiceField(choices=ControlPlanRankingCriterion.choices),
        default=lambda: list(ControlPlanRankingCriterion.values),
    )

    def validate_validation_statuses(self, value):
        return _unique(value, "Un état de conformité est choisi deux fois")

    def validate_ranking_criteria(self, value):
        return _unique(value, "Un critère de classement est choisi deux fois")

    def validate_custom_zone_groups(self, value):
        _unique(
            [uuid for group in value for uuid in group],
            "Une zone à enjeux est choisie deux fois",
        )
        return value

    @staticmethod
    def to_storage(validated_data: dict) -> dict:
        """JSON-ready (uuids as strings), snake_case like the rest of the stored data."""
        return {
            **validated_data,
            "communes_uuids": [str(uuid) for uuid in validated_data["communes_uuids"]],
            "epcis_uuids": [str(uuid) for uuid in validated_data["epcis_uuids"]],
            "object_types_uuids": [
                str(uuid) for uuid in validated_data["object_types_uuids"]
            ],
            "custom_zone_groups": [
                [str(uuid) for uuid in group]
                for group in validated_data["custom_zone_groups"]
            ],
        }


class ControlPlanWaveInputSerializer(serializers.Serializer):
    control_plan_uuid = serializers.UUIDField()
    parcels_count = serializers.IntegerField(min_value=1, max_value=MAX_PARCELS_COUNT)
    criteria = ControlPlanCriteriaSerializer()


class ControlPlanEligibleCountInputSerializer(serializers.Serializer):
    criteria = ControlPlanCriteriaSerializer()


class ControlPlanWaveUpdateSerializer(serializers.Serializer):
    parcels_count = serializers.IntegerField(
        min_value=1, max_value=MAX_PARCELS_COUNT, required=False
    )
    criteria = ControlPlanCriteriaSerializer(required=False)


class ControlPlanWaveSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = ControlPlanWave
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "control_plan_uuid",
            "number",
            "control_plan_wave_status",
            "criteria",
            "parcels_count",
            "eligible_parcels_count",
            "computed_at",
            "validated_at",
            "proposal",
        ]

    control_plan_uuid = serializers.UUIDField(
        source="control_plan.uuid", read_only=True
    )
    proposal = serializers.SerializerMethodField()

    def get_proposal(self, obj: ControlPlanWave):
        from core.services.control_plan import ControlPlanWaveService

        return ControlPlanWaveService.proposal_summary(obj)


class ControlPlanValidationResultSerializer(serializers.Serializer):
    planned_parcels_count = serializers.IntegerField()
    switched_objects_count = serializers.IntegerField()
    skipped_parcels = serializers.ListField(child=serializers.DictField())


class ControlPlanInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs):
        start_date = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end_date = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "La fin de la période précède son début"}
            )
        return attrs


class ControlPlanCreateSerializer(ControlPlanInputSerializer):
    user_group_uuid = serializers.UUIDField()


class ControlPlanSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = ControlPlan
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "start_date",
            "end_date",
            "control_plan_status",
            "user_group",
            "closed_at",
            "is_expired",
            "can_edit",
            "validated_waves_count",
            "draft_wave",
            "last_validated_wave",
            "counters",
        ]

    user_group = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    validated_waves_count = serializers.SerializerMethodField()
    draft_wave = serializers.SerializerMethodField()
    # its criteria prefill the next wave
    last_validated_wave = serializers.SerializerMethodField()
    counters = serializers.SerializerMethodField()

    def get_user_group(self, obj: ControlPlan):
        return {"uuid": obj.user_group.uuid, "name": obj.user_group.name}

    def get_is_expired(self, obj: ControlPlan):
        return (
            obj.control_plan_status == ControlPlanStatus.ACTIVE
            and obj.end_date < timezone.localdate()
        )

    def get_can_edit(self, obj: ControlPlan):
        permission = self.context["control_plan_permission"]
        return (
            obj.control_plan_status == ControlPlanStatus.ACTIVE
            and permission.can_edit(obj.user_group)
        )

    def get_validated_waves_count(self, obj: ControlPlan):
        return obj.waves.filter(
            control_plan_wave_status=ControlPlanWaveStatus.VALIDATED
        ).count()

    def get_draft_wave(self, obj: ControlPlan):
        draft = obj.waves.filter(
            control_plan_wave_status=ControlPlanWaveStatus.DRAFT
        ).first()
        if draft is None:
            return None
        return ControlPlanWaveSerializer(draft, context=self.context).data

    def get_last_validated_wave(self, obj: ControlPlan):
        wave = (
            obj.waves.filter(control_plan_wave_status=ControlPlanWaveStatus.VALIDATED)
            .order_by("-number")
            .first()
        )
        if wave is None:
            return None
        return ControlPlanWaveSerializer(wave, context=self.context).data

    def get_counters(self, obj: ControlPlan):
        from core.services.control_plan import ControlPlanService

        return ControlPlanService.counters(obj)


class ControlPlanParcelSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlPlanParcel
        fields = [
            "uuid",
            "control_plan_parcel_status",
            "rank",
            "wave_number",
            "parcel_uuid",
            "id_parcellaire",
            "prefix",
            "section",
            "num_parcel",
            "commune",
            "objects_count",
            "new_objects_count",
            "unverified_objects_count",
            "zone_priority",
            "zone_names",
            "object_types",
            "detection_object_uuids",
            "follow_up_status",
            "status_changed_at",
        ]

    wave_number = serializers.IntegerField(source="wave.number", default=None)
    parcel_uuid = serializers.UUIDField(source="parcel.uuid", default=None)
    commune = serializers.SerializerMethodField()
    zone_names = serializers.SerializerMethodField()
    object_types = serializers.SerializerMethodField()
    detection_object_uuids = serializers.SerializerMethodField()
    follow_up_status = serializers.SerializerMethodField()

    def get_commune(self, obj: ControlPlanParcel):
        if obj.commune is None:
            return None
        return {
            "uuid": obj.commune.uuid,
            "name": obj.commune.name,
            "code": obj.commune.iso_code,
        }

    def get_zone_names(self, obj: ControlPlanParcel):
        return obj.summary.get("zone_names", [])

    def get_object_types(self, obj: ControlPlanParcel):
        return obj.summary.get("object_types", [])

    def get_detection_object_uuids(self, obj: ControlPlanParcel):
        return obj.summary.get("detection_object_uuids", [])

    def get_follow_up_status(self, obj: ControlPlanParcel):
        from core.services.control_plan import ControlPlanParcelService

        return ControlPlanParcelService.follow_up_status(obj)


class ControlPlanOutOfPlanParcelSerializer(ParcelListItemSerializer):
    class Meta(ParcelListItemSerializer.Meta):
        fields = ParcelListItemSerializer.Meta.fields + ["detection_object_uuids"]

    detection_object_uuids = serializers.SerializerMethodField()

    def get_detection_object_uuids(self, obj):
        # the filtered prefetch: .all() would query again without the filters
        detection_objects = getattr(obj, "_prefetched_objects_cache", {}).get(
            "detection_objects", []
        )
        return [str(detection_object.uuid) for detection_object in detection_objects]


class ControlPlanGroupSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    user_group_type = serializers.CharField()
    can_edit = serializers.BooleanField()
    active_control_plan_uuid = serializers.UUIDField(allow_null=True)
