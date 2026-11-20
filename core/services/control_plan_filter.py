"""The « Uniquement mes plans de contrôle » filter (`controlPlan=true`) of the map, the
detection list and the parcel table, narrowed to one plan by `controlPlanUuid`."""

import uuid
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
CONTROL_PLAN_UUID_PARAM = "controlPlanUuid"


def is_control_plan_filter_requested(params) -> bool:
    return params.get(CONTROL_PLAN_PARAM) == "true"


def _parse_uuid(value) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


def control_plan_q(
    user,
    scoped_user_group,
    detection_object_prefix: str,
    detection_prefix: str,
    control_plan_uuid: Optional[str] = None,
) -> Optional[Q]:
    """Detections on a parcel planned in an active plan of the caller's groups, or that
    are « À contrôler » themselves (the parcels set to control outside the plans), in
    one of these groups' zones à enjeux: the plans ignore everything outside them.

    With `control_plan_uuid`, only the parcels planned by that active plan, in its
    group's zones: nothing when the caller cannot see it, or it is closed.

    `detection_object_prefix` / `detection_prefix` lead from the filtered model to the
    detection object and to the detection, as in TileSetPermission._get_last_detections_filters.
    None when the caller has no access to the control plans: the filter is then ignored."""
    accessible_groups = ControlPlanPermission(
        user=user, scoped_user_group=scoped_user_group
    ).accessible_groups()
    if not accessible_groups.exists():
        return None

    planned = ControlPlanParcel.objects.filter(
        control_plan_parcel_status=ControlPlanParcelStatus.PLANNED,
        control_plan__control_plan_status=ControlPlanStatus.ACTIVE,
        control_plan__deleted=False,
        control_plan__user_group__in=accessible_groups,
        parcel_id__isnull=False,
    )
    zones = GeoCustomZone.objects.active().filter(
        user_groups_custom_geo_zones__in=accessible_groups
    )

    if control_plan_uuid:
        plan_uuid = _parse_uuid(control_plan_uuid)
        if plan_uuid is None:
            return Q(pk__in=[])
        planned = planned.filter(control_plan__uuid=plan_uuid)
        zones = GeoCustomZone.objects.active().filter(
            user_groups_custom_geo_zones__control_plans__uuid=plan_uuid
        )

    in_zones_object_ids = DetectionObject.geo_custom_zones.through.objects.filter(
        geocustomzone_id__in=zones.values("id")
    ).values("detectionobject_id")
    planned_q = Q(
        **{f"{detection_object_prefix}parcel_id__in": planned.values("parcel_id")}
    )
    if not control_plan_uuid:
        planned_q |= Q(
            **{
                f"{detection_prefix}detection_data__detection_control_status": DetectionControlStatus.TO_CONTROL
            }
        )

    return planned_q & Q(**{f"{detection_object_prefix}id__in": in_zones_object_ids})
