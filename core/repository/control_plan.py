"""Querysets behind the control plan.

The « current » detection of an object is its most recent one on a BACKGROUND or
PARTIAL tile set that is not deactivated, ties broken by id. Every status check of the
plan (eligibility, switch, follow-up, removal) reads it, so a plan never judges an
object on an older row than the one an agent edits. The last-tile-sets filter of the
map only gates visibility: a BACKGROUND tile set is not hidden by a newer PARTIAL one,
so an object can have two « last » detections there.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from django.db.models import Exists, OuterRef, Q, QuerySet

from core.constants.control_plan import (
    CLOSED_VALIDATION_STATUSES,
    CONTROLLED_STATUSES,
    CURRENT_DETECTION_TILE_SET_TYPES,
    EXCLUDED_TILE_SET_STATUSES,
    OFFICIAL_REPORT_CONTROL_STATUSES,
)
from core.models.control_plan import (
    ControlPlan,
    ControlPlanParcel,
    ControlPlanParcelObject,
    ControlPlanParcelStatus,
)
from core.models.detection import Detection, DetectionSource
from core.models.detection_authorization import DetectionAuthorization
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
)
from core.models.detection_object import DetectionObject
from core.models.geo_commune import GeoCommune
from core.models.geo_zone import GeoZone
from core.models.tile_set import TileSetStatus, TileSetType
from core.models.user import User
from core.models.user_group import UserGroup
from core.permissions.user import communes_reachable_from

# detections drawn or forced visible by an agent bypass the score threshold, as on the map
SCORE_BYPASS_SOURCES = [
    DetectionSource.INTERFACE_DRAWN,
    DetectionSource.INTERFACE_FORCED_VISIBLE,
]

# Postgres caps the number of bind parameters of a query
IN_CHUNK_SIZE = 10000


@dataclass
class EligibilityCriteria:
    """The criteria of a wave, resolved to ids against the group."""

    # perimeter inside the territory; None for the whole territory
    commune_ids: Optional[List[int]]
    object_type_uuids: List[str]
    # ObjectType id → priority (0 first); the « Autres » types share one
    object_type_ranks: Dict[int, int]
    score_min: float
    validation_statuses: List[str]
    include_prescribed: bool
    # GeoZone ids of the selected zones à enjeux, by priority
    zone_groups: List[List[int]]
    exclude_authorized_parcels: bool
    exclude_official_report_parcels: bool
    min_objects_count: int
    ranking_criteria: List[str]

    @property
    def zone_ids(self) -> List[int]:
        return [zone_id for group in self.zone_groups for zone_id in group]


def current_detections(queryset: Optional[QuerySet] = None) -> QuerySet[Detection]:
    queryset = Detection.objects.all() if queryset is None else queryset
    newer = Detection.objects.filter(
        detection_object_id=OuterRef("detection_object_id"),
        tile_set__tile_set_type__in=CURRENT_DETECTION_TILE_SET_TYPES,
    ).exclude(tile_set__tile_set_status__in=EXCLUDED_TILE_SET_STATUSES)
    newer = newer.filter(
        Q(tile_set__date__gt=OuterRef("tile_set__date"))
        | Q(tile_set__date=OuterRef("tile_set__date"), id__gt=OuterRef("id"))
    )

    return (
        queryset.filter(tile_set__tile_set_type__in=CURRENT_DETECTION_TILE_SET_TYPES)
        .exclude(tile_set__tile_set_status__in=EXCLUDED_TILE_SET_STATUSES)
        .filter(~Exists(newer))
    )


def is_new_object() -> Exists:
    """True on a detection whose object was seen on no earlier tile set."""
    older = Detection.objects.filter(
        detection_object_id=OuterRef("detection_object_id"),
        tile_set__date__lt=OuterRef("tile_set__date"),
        tile_set__tile_set_type__in=CURRENT_DETECTION_TILE_SET_TYPES,
    ).exclude(tile_set__tile_set_status__in=EXCLUDED_TILE_SET_STATUSES)
    return ~Exists(older)


def territory_communes(user_group: UserGroup) -> QuerySet[GeoCommune]:
    return communes_reachable_from(GeoZone.objects.filter(user_groups=user_group))


def _communes_filter(user_group: UserGroup, commune_ids: Optional[List[int]]):
    if commune_ids is None:
        return territory_communes(user_group).values("id")
    return commune_ids


def visible_current_detections(
    user: User, user_group: UserGroup, commune_ids: Optional[List[int]] = None
) -> QuerySet[Detection]:
    """Current detections the group sees on its last tile sets, on its territory (or the
    given communes of it), as the map shows them to the group's members."""
    from core.permissions.tile_set import TileSetPermission

    last_detections_q = TileSetPermission(
        user=user, scoped_user_group=user_group
    ).get_last_detections_filters_detections(
        filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
        filter_tile_set_status_in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN],
        filter_has_collectivities=True,
    )
    if last_detections_q is None:
        return Detection.objects.none()

    # The tile-set filter is no territorial bound: a regional tile set reaches the
    # whole region.
    queryset = Detection.objects.filter(last_detections_q).filter(
        detection_object__commune_id__in=_communes_filter(user_group, commune_ids)
    )
    return current_detections(queryset)


def in_zones_or_drawn(queryset: QuerySet, zone_ids: List[int]) -> QuerySet:
    """In one of the zones, or drawn by an agent: the map's default (« ALL »)."""
    in_zones = Exists(
        DetectionObject.geo_custom_zones.through.objects.filter(
            detectionobject_id=OuterRef("detection_object_id"),
            geocustomzone_id__in=zone_ids,
        )
    )
    return queryset.annotate(in_selected_zones=in_zones).filter(
        Q(in_selected_zones=True) | Q(detection_source=DetectionSource.INTERFACE_DRAWN)
    )


def score_at_least(queryset: QuerySet, score_min: float) -> QuerySet:
    return queryset.filter(
        Q(score__gte=score_min) | Q(detection_source__in=SCORE_BYPASS_SOURCES)
    )


def exclude_prescribed(queryset: QuerySet) -> QuerySet:
    # exclude() keeps the NULL statuses
    return queryset.exclude(
        detection_data__detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED
    )


def parcels_taken_by_plan(
    control_plan: ControlPlan, ranked_draft_id: Optional[int] = None
) -> QuerySet:
    """Parcels a new computation must skip: planned, excluded or removed ones. The
    exclusions of `ranked_draft_id` are ranked anyway, to keep their place in it."""
    taken = ControlPlanParcel.objects.filter(
        control_plan=control_plan, parcel_id__isnull=False
    ).exclude(control_plan_parcel_status=ControlPlanParcelStatus.PROPOSED)
    if ranked_draft_id is not None:
        taken = taken.exclude(
            wave_id=ranked_draft_id,
            control_plan_parcel_status=ControlPlanParcelStatus.EXCLUDED,
        )
    return taken.values("parcel_id")


def eligible_detections(
    user: User,
    user_group: UserGroup,
    criteria: EligibilityCriteria,
    control_plan: Optional[ControlPlan] = None,
    parcel_ids: Optional[List[int]] = None,
    ranked_draft_id: Optional[int] = None,
) -> QuerySet[Detection]:
    """One row per eligible object: its current detection."""
    queryset = visible_current_detections(user, user_group, criteria.commune_ids)
    queryset = queryset.filter(
        detection_object__parcel__isnull=False,
        # an object near a boundary can sit on a parcel of the neighbouring commune
        detection_object__parcel__commune_id__in=_communes_filter(
            user_group, criteria.commune_ids
        ),
        detection_object__object_type__uuid__in=criteria.object_type_uuids,
        detection_data__detection_validation_status__in=criteria.validation_statuses,
        detection_data__detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
    )
    queryset = score_at_least(queryset, criteria.score_min)
    queryset = in_zones_or_drawn(queryset, criteria.zone_ids)

    if not criteria.include_prescribed:
        queryset = exclude_prescribed(queryset)

    if control_plan is not None:
        queryset = queryset.exclude(
            detection_object__parcel_id__in=parcels_taken_by_plan(
                control_plan, ranked_draft_id
            )
        )

    if parcel_ids is not None:
        queryset = queryset.filter(detection_object__parcel_id__in=parcel_ids)

    return queryset


def _chunks(ids: Iterable[int]) -> Iterable[List[int]]:
    ids = list(ids)
    for start in range(0, len(ids), IN_CHUNK_SIZE):
        yield ids[start : start + IN_CHUNK_SIZE]


def parcels_with_official_report(parcel_ids: Iterable[int]) -> Set[int]:
    """Parcels where an object is, or was, under an official report or what follows."""
    found = set()
    for chunk in _chunks(parcel_ids):
        found.update(
            Detection.objects.filter(detection_object__parcel_id__in=chunk)
            .filter(
                Q(
                    detection_data__detection_control_status__in=OFFICIAL_REPORT_CONTROL_STATUSES
                )
                | Q(detection_data__official_report_date__isnull=False)
            )
            .values_list("detection_object__parcel_id", flat=True)
            .distinct()
        )
    return found


def parcels_with_authorization(parcel_ids: Iterable[int]) -> Set[int]:
    found = set()
    for chunk in _chunks(parcel_ids):
        found.update(
            DetectionAuthorization.objects.filter(
                deleted=False,
                detection_data__detection__detection_object__parcel_id__in=chunk,
            )
            .values_list(
                "detection_data__detection__detection_object__parcel_id", flat=True
            )
            .distinct()
        )
    return found


def zone_memberships(
    detection_object_ids: QuerySet, zone_ids: List[int]
) -> List[Tuple[int, int]]:
    """(object id, zone id) for the objects in one of the zones."""
    return list(
        DetectionObject.geo_custom_zones.through.objects.filter(
            detectionobject_id__in=detection_object_ids,
            geocustomzone_id__in=zone_ids,
        ).values_list("detectionobject_id", "geocustomzone_id")
    )


def follow_up_annotations() -> dict:
    """On ControlPlanParcel: whether one of its objects is still to control, and whether
    one was controlled (or found legal / a false detection)."""
    plan_objects = ControlPlanParcelObject.objects.filter(
        control_plan_parcel_id=OuterRef("pk")
    )
    to_control = (
        current_detections()
        .filter(
            detection_object_id=OuterRef("detection_object_id"),
            detection_data__detection_control_status=DetectionControlStatus.TO_CONTROL,
        )
        .exclude(
            detection_data__detection_validation_status__in=CLOSED_VALIDATION_STATUSES
        )
    )
    controlled = (
        current_detections()
        .filter(detection_object_id=OuterRef("detection_object_id"))
        .filter(
            Q(detection_data__detection_control_status__in=CONTROLLED_STATUSES)
            | Q(
                detection_data__detection_validation_status__in=CLOSED_VALIDATION_STATUSES
            )
        )
    )

    return {
        "has_to_control": Exists(plan_objects.filter(Exists(to_control))),
        "has_controlled": Exists(plan_objects.filter(Exists(controlled))),
    }
