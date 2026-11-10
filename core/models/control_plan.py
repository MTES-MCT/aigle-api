from django.db import models

from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from core.models.detection_data import DetectionValidationStatus
from core.models.detection_object import DetectionObject
from core.models.geo_commune import GeoCommune
from core.models.parcel import Parcel
from core.models.user import User
from core.models.user_group import UserGroup


class ControlPlanStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "ACTIVE"
    CLOSED = "CLOSED", "CLOSED"


class ControlPlan(TimestampedModelMixin, UuidModelMixin, DeletableModelMixin):
    """The control plan of a user group over a period, shared by its members."""

    name = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    user_group = models.ForeignKey(
        UserGroup, related_name="control_plans", on_delete=models.CASCADE
    )
    start_date = models.DateField()
    end_date = models.DateField()
    control_plan_status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=ControlPlanStatus.choices,
        default=ControlPlanStatus.ACTIVE,
    )
    created_by = models.ForeignKey(
        User, related_name="+", on_delete=models.SET_NULL, null=True
    )
    closed_by = models.ForeignKey(
        User, related_name="+", on_delete=models.SET_NULL, null=True
    )
    closed_at = models.DateTimeField(null=True)

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + []
        constraints = [
            models.UniqueConstraint(
                fields=["user_group"],
                condition=models.Q(
                    control_plan_status=ControlPlanStatus.ACTIVE, deleted=False
                ),
                name="control_plan_one_active_per_group",
            ),
            models.CheckConstraint(
                check=models.Q(end_date__gte=models.F("start_date")),
                name="control_plan_end_after_start",
            ),
        ]


class ControlPlanWaveStatus(models.TextChoices):
    DRAFT = "DRAFT", "DRAFT"
    VALIDATED = "VALIDATED", "VALIDATED"


class ControlPlanWave(TimestampedModelMixin, UuidModelMixin):
    """One run of the process: criteria, the ranked proposal, then its validation.

    A draft is recomputed or dropped, never archived, hence no soft delete."""

    control_plan = models.ForeignKey(
        ControlPlan, related_name="waves", on_delete=models.CASCADE
    )
    number = models.PositiveIntegerField()
    control_plan_wave_status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=ControlPlanWaveStatus.choices,
        default=ControlPlanWaveStatus.DRAFT,
    )
    # validated by ControlPlanCriteriaSerializer, stored snake_case
    criteria = models.JSONField()
    parcels_count = models.PositiveIntegerField()
    eligible_parcels_count = models.PositiveIntegerField(default=0)
    computed_at = models.DateTimeField(null=True)
    created_by = models.ForeignKey(
        User, related_name="+", on_delete=models.SET_NULL, null=True
    )
    validated_by = models.ForeignKey(
        User, related_name="+", on_delete=models.SET_NULL, null=True
    )
    validated_at = models.DateTimeField(null=True)

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + []
        constraints = [
            models.UniqueConstraint(
                fields=["control_plan", "number"],
                name="control_plan_wave_number_unique",
            ),
            models.UniqueConstraint(
                fields=["control_plan"],
                condition=models.Q(
                    control_plan_wave_status=ControlPlanWaveStatus.DRAFT
                ),
                name="control_plan_one_draft_wave",
            ),
        ]


class ControlPlanParcelStatus(models.TextChoices):
    PROPOSED = "PROPOSED", "PROPOSED"
    EXCLUDED = "EXCLUDED", "EXCLUDED"
    PLANNED = "PLANNED", "PLANNED"
    REMOVED = "REMOVED", "REMOVED"


class ControlPlanParcel(TimestampedModelMixin, UuidModelMixin):
    """A parcel of a plan: proposed by a draft, excluded by an agent, planned once the
    wave is validated, or removed afterwards. A parcel appears once per plan."""

    control_plan = models.ForeignKey(
        ControlPlan, related_name="control_plan_parcels", on_delete=models.CASCADE
    )
    # null once the draft that excluded it was dropped: the exclusion stays for the plan
    wave = models.ForeignKey(
        ControlPlanWave,
        related_name="control_plan_parcels",
        on_delete=models.SET_NULL,
        null=True,
    )
    # SET_NULL + the cadastral snapshot below: a cadastre re-import may delete the parcel
    parcel = models.ForeignKey(
        Parcel,
        related_name="control_plan_parcels",
        on_delete=models.SET_NULL,
        null=True,
    )
    id_parcellaire = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    prefix = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    section = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    num_parcel = models.IntegerField()
    commune = models.ForeignKey(
        GeoCommune, related_name="+", on_delete=models.SET_NULL, null=True
    )
    control_plan_parcel_status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH, choices=ControlPlanParcelStatus.choices
    )
    rank = models.PositiveIntegerField()
    # what the ranking saw, kept to explain the rank
    objects_count = models.PositiveIntegerField(default=0)
    new_objects_count = models.PositiveIntegerField(default=0)
    unverified_objects_count = models.PositiveIntegerField(default=0)
    zone_priority = models.PositiveIntegerField(null=True)
    # {"zone_names": [...], "object_types": [{uuid, name, color, count}], "detection_object_uuids": [...]}
    summary = models.JSONField(default=dict)
    status_changed_by = models.ForeignKey(
        User, related_name="+", on_delete=models.SET_NULL, null=True
    )
    status_changed_at = models.DateTimeField(null=True)

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + [
            models.Index(fields=["wave", "control_plan_parcel_status", "rank"]),
            models.Index(fields=["control_plan", "control_plan_parcel_status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["control_plan", "parcel"], name="control_plan_parcel_unique"
            ),
        ]


class ControlPlanParcelObject(models.Model):
    """An object the plan switched to « À contrôler », with what to restore on removal."""

    control_plan_parcel = models.ForeignKey(
        ControlPlanParcel,
        related_name="control_plan_parcel_objects",
        on_delete=models.CASCADE,
    )
    detection_object = models.ForeignKey(
        DetectionObject,
        related_name="control_plan_parcel_objects",
        on_delete=models.CASCADE,
    )
    previous_validation_status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH, choices=DetectionValidationStatus.choices
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["control_plan_parcel", "detection_object"],
                name="control_plan_parcel_object_unique",
            ),
        ]
