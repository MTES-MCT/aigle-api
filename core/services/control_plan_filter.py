"""The « Uniquement mon plan de contrôle » filter (`controlPlan=true`) of the map, the
detection list and the parcel table."""

from typing import Optional

from django.db.models import Q

from core.models.control_plan import (
    ControlPlanParcel,
    ControlPlanParcelStatus,
    ControlPlanStatus,
)
from core.models.detection_data import DetectionControlStatus
from core.models.detection_object import DetectionObject
from core.models.geo_custom_zone import GeoCustomZone
from core.permissions.control_plan import ControlPlanPermission

CONTROL_PLAN_PARAM = "controlPlan"


def is_control_plan_filter_requested(params) -> bool:
    return params.get(CONTROL_PLAN_PARAM) == "true"


def control_plan_q(
    user,
    scoped_user_group,
    detection_object_prefix: str,
    detection_prefix: str,
) -> Optional[Q]:
    """Detections on a parcel planned in an active plan of the caller's groups, or that
    are « À contrôler » themselves (the parcels set to control outside the plan), in one
    of these groups' zones à enjeux: the plan ignores everything outside them.

    `detection_object_prefix` / `detection_prefix` lead from the filtered model to the
    detection object and to the detection, as in TileSetPermission._get_last_detections_filters.
    None when the caller has no access to the control plans: the filter is then ignored."""
    accessible_groups = ControlPlanPermission(
        user=user, scoped_user_group=scoped_user_group
    ).accessible_groups()
    if not accessible_groups.exists():
        return None

    planned_parcel_ids = ControlPlanParcel.objects.filter(
        control_plan_parcel_status=ControlPlanParcelStatus.PLANNED,
        control_plan__control_plan_status=ControlPlanStatus.ACTIVE,
        control_plan__deleted=False,
        control_plan__user_group__in=accessible_groups,
        parcel_id__isnull=False,
    ).values("parcel_id")

    in_zones_object_ids = DetectionObject.geo_custom_zones.through.objects.filter(
        geocustomzone_id__in=GeoCustomZone.objects.active()
        .filter(user_groups_custom_geo_zones__in=accessible_groups)
        .values("id")
    ).values("detectionobject_id")

    return (
        Q(**{f"{detection_object_prefix}parcel_id__in": planned_parcel_ids})
        | Q(
            **{
                f"{detection_prefix}detection_data__detection_control_status": DetectionControlStatus.TO_CONTROL
            }
        )
    ) & Q(**{f"{detection_object_prefix}id__in": in_zones_object_ids})
