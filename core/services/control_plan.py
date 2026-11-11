"""Control plans: a group's plan over a period, built wave after wave (criteria → ranked
proposal → adjustments → validation that sets the objects « À contrôler »), then followed
up as the controls go on."""

import json
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from django.contrib.gis.geos import GeometryCollection
from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import Count, F, Max, Q, QuerySet
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from simple_history.utils import bulk_update_with_history

from core.constants.control_plan import (
    CONTROL_PLAN_HISTORY_CHANGE_REASON,
    DEFAULT_SCORE_MIN,
    MIN_WAITING_LIST_SIZE,
    PROPOSAL_STATEMENT_TIMEOUT_MS,
    ControlPlanFollowUpStatus,
    ControlPlanParcelSection,
    ControlPlanRankingCriterion,
)
from core.models.control_plan import (
    ControlPlan,
    ControlPlanParcel,
    ControlPlanParcelObject,
    ControlPlanParcelStatus,
    ControlPlanStatus,
    ControlPlanWave,
    ControlPlanWaveStatus,
)
from core.models.detection import Detection
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionValidationStatus,
)
from core.models.geo_commune import GeoCommune
from core.models.geo_epci import GeoEpci
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.geo_custom_zone import GeoCustomZone
from core.models.object_type import ObjectType
from core.models.object_type_category import ObjectTypeCategoryObjectTypeStatus
from core.models.parcel import Parcel
from core.models.user import User
from core.models.user_group import UserGroup, UserGroupType
from core.permissions.control_plan import ControlPlanPermission
from core.permissions.detection import DetectionPermission
from core.permissions.user import UserPermission
from core.repository.control_plan import (
    EligibilityCriteria,
    current_detections,
    eligible_detections,
    exclude_prescribed,
    follow_up_annotations,
    in_zones_or_drawn,
    is_new_object,
    parcels_with_authorization,
    parcels_with_official_report,
    score_at_least,
    territory_communes,
    visible_current_detections,
    zone_memberships,
)
from core.utils.cache import invalidate_count_caches
from core.utils.exceptions import Conflict

# the ids shown with a parcel to open it on the map
MAX_DETECTION_OBJECT_UUIDS = 50

DETECTION_DATA_SWITCHED_FIELDS = [
    "detection_control_status",
    # set_detection_control_status cascades to these two: bulk_update must write them
    "detection_validation_status",
    "detection_prescription_status",
    "user_last_update",
    # bulk_update skips auto_now
    "updated_at",
]

CLOSED_PLAN_MESSAGE = "Ce plan de contrôle est clôturé"
NOT_A_DRAFT_MESSAGE = "Cette vague a déjà été validée"
DROPPED_DRAFT_MESSAGE = "Cette proposition a été abandonnée entre-temps"


class ProposalTimeout(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = (
        "Le calcul de la proposition a pris trop de temps : réduisez le périmètre ou "
        "le nombre de zones à enjeux, puis réessayez."
    )
    default_code = "control_plan_proposal_timeout"


def _invalidate_counts_on_commit():
    # the controlPlan filter reads plan rows the count cache key (the SQL) does not show
    transaction.on_commit(invalidate_count_caches)


def group_zones(user_group: UserGroup) -> QuerySet[GeoCustomZone]:
    return GeoCustomZone.objects.active().filter(
        user_groups_custom_geo_zones=user_group
    )


def plan_object_types(
    user: User,
    request_scoped_user_group: Optional[UserGroup],
    user_group: UserGroup,
) -> List[Tuple[ObjectType, ObjectTypeCategoryObjectTypeStatus]]:
    """The object types of the plan's group, shared by all its members. A group without
    object type categories (many today) falls back to the caller's types, as on the map."""
    return (
        UserPermission(
            user=user, scoped_user_group=user_group
        ).get_user_object_types_with_status()
        or UserPermission(
            user=user, scoped_user_group=request_scoped_user_group
        ).get_user_object_types_with_status()
    )


# ----------------------------------------------------------------------- criteria


def _resolve_perimeter(
    criteria: dict, user_group: UserGroup, errors: dict
) -> Optional[List[int]]:
    communes_uuids = [str(uuid) for uuid in criteria.get("communes_uuids") or []]
    epcis_uuids = [str(uuid) for uuid in criteria.get("epcis_uuids") or []]
    if not communes_uuids and not epcis_uuids:
        return None

    territory_ids = set(territory_communes(user_group).values_list("id", flat=True))
    commune_ids = set()

    requested = {
        str(uuid): commune_id
        for uuid, commune_id in GeoCommune.objects.filter(
            uuid__in=communes_uuids
        ).values_list("uuid", "id")
    }
    for commune_uuid in communes_uuids:
        commune_id = requested.get(commune_uuid)
        if commune_id not in territory_ids:
            errors["communes_uuids"] = [
                "Une des communes choisies ne fait pas partie du territoire du groupe"
            ]
            continue
        commune_ids.add(commune_id)

    communes_by_epci = defaultdict(set)
    for epci_uuid, commune_id in GeoCommune.objects.filter(
        epci__uuid__in=epcis_uuids
    ).values_list("epci__uuid", "id"):
        communes_by_epci[str(epci_uuid)].add(commune_id)
    for epci_uuid in epcis_uuids:
        inside = communes_by_epci[epci_uuid] & territory_ids
        if not inside:
            errors["epcis_uuids"] = [
                "Un des EPCI choisis ne fait pas partie du territoire du groupe"
            ]
            continue
        # an EPCI straddling the territory keeps its communes inside
        commune_ids |= inside

    return sorted(commune_ids)


def _resolve_zone_groups(
    criteria: dict, user_group: UserGroup, errors: dict
) -> List[List[int]]:
    groups = [[str(uuid) for uuid in group] for group in criteria["custom_zone_groups"]]
    requested = {uuid for group in groups for uuid in group}
    zone_ids = {
        str(uuid): zone_id
        for uuid, zone_id in group_zones(user_group)
        .filter(uuid__in=requested)
        .values_list("uuid", "id")
    }
    if len(zone_ids) != len(requested):
        errors["custom_zone_groups"] = [
            "Une des zones à enjeux choisies est désactivée ou n'est pas ouverte au groupe"
        ]

    return [[zone_ids[uuid] for uuid in group if uuid in zone_ids] for group in groups]


def resolve_criteria(
    criteria: dict,
    user: User,
    request_scoped_user_group: Optional[UserGroup],
    user_group: UserGroup,
) -> EligibilityCriteria:
    """The stored criteria, checked against the group as it is now (a zone may have been
    deactivated since). Raises a 400 keyed under `criteria`."""
    errors = {}
    commune_ids = _resolve_perimeter(criteria, user_group, errors)
    zone_groups = _resolve_zone_groups(criteria, user_group, errors)

    allowed_uuids = {
        str(object_type.uuid)
        for object_type, _ in plan_object_types(
            user, request_scoped_user_group, user_group
        )
    }
    object_type_uuids = [
        str(uuid)
        for uuid in criteria["object_types_uuids"]
        if str(uuid) in allowed_uuids
    ]
    if not object_type_uuids:
        errors["object_types_uuids"] = [
            "Aucun des types d'objets choisis n'est ouvert au groupe"
        ]

    if errors:
        raise ValidationError({"criteria": errors})

    validation_statuses = list(criteria["validation_statuses"])
    # ILLEGAL is not selectable any more but still in data: it rides with SUSPECT
    if DetectionValidationStatus.SUSPECT in validation_statuses:
        validation_statuses.append(DetectionValidationStatus.ILLEGAL)

    return EligibilityCriteria(
        commune_ids=commune_ids,
        object_type_uuids=object_type_uuids,
        score_min=criteria["score_min"],
        validation_statuses=validation_statuses,
        include_prescribed=criteria["include_prescribed"],
        zone_groups=zone_groups,
        exclude_authorized_parcels=criteria["exclude_authorized_parcels"],
        exclude_official_report_parcels=criteria["exclude_official_report_parcels"],
        min_objects_count=criteria["min_objects_count"],
        # a wave stored before a criterion was dropped may still name it
        ranking_criteria=[
            criterion
            for criterion in criteria["ranking_criteria"]
            if criterion in ControlPlanRankingCriterion.values
        ],
    )


# ----------------------------------------------------------------------- proposal


@dataclass
class _CandidateObject:
    uuid: str
    object_type_id: int
    detection_data_id: int
    validation_status: str
    is_new: bool


@dataclass
class _ParcelCandidate:
    parcel_id: int
    objects: Dict[int, _CandidateObject] = field(default_factory=dict)
    zone_groups: Set[int] = field(default_factory=set)

    @property
    def new_objects_count(self) -> int:
        return sum(1 for obj in self.objects.values() if obj.is_new)

    @property
    def unverified_objects_count(self) -> int:
        return sum(
            1
            for obj in self.objects.values()
            if obj.validation_status == DetectionValidationStatus.DETECTED_NOT_VERIFIED
        )


def _collect_candidates(
    user: User,
    user_group: UserGroup,
    criteria: EligibilityCriteria,
    control_plan: ControlPlan,
    parcel_ids: Optional[List[int]] = None,
    ranked_draft_id: Optional[int] = None,
) -> Dict[int, _ParcelCandidate]:
    detections = eligible_detections(
        user,
        user_group,
        criteria,
        control_plan=control_plan,
        parcel_ids=parcel_ids,
        ranked_draft_id=ranked_draft_id,
    )
    rows = detections.annotate(is_new=is_new_object()).values_list(
        "detection_object__parcel_id",
        "detection_object_id",
        "detection_object__uuid",
        "detection_object__object_type_id",
        "detection_data_id",
        "detection_data__detection_validation_status",
        "is_new",
    )

    candidates: Dict[int, _ParcelCandidate] = {}
    for (
        parcel_id,
        object_id,
        object_uuid,
        object_type_id,
        detection_data_id,
        validation_status,
        is_new,
    ) in rows.iterator(chunk_size=5000):
        candidates.setdefault(parcel_id, _ParcelCandidate(parcel_id)).objects[
            object_id
        ] = _CandidateObject(
            uuid=str(object_uuid),
            object_type_id=object_type_id,
            detection_data_id=detection_data_id,
            validation_status=validation_status,
            is_new=is_new,
        )

    if not candidates:
        return {}

    group_by_zone = {
        zone_id: index
        for index, group in enumerate(criteria.zone_groups)
        for zone_id in group
    }
    parcel_by_object = {
        object_id: candidate.parcel_id
        for candidate in candidates.values()
        for object_id in candidate.objects
    }
    object_ids = list(parcel_by_object)
    for start in range(0, len(object_ids), 10000):
        for object_id, zone_id in zone_memberships(
            object_ids[start : start + 10000], criteria.zone_ids
        ):
            candidates[parcel_by_object[object_id]].zone_groups.add(
                group_by_zone[zone_id]
            )

    excluded = set()
    if criteria.exclude_official_report_parcels:
        excluded |= parcels_with_official_report(candidates.keys())
    if criteria.exclude_authorized_parcels:
        excluded |= parcels_with_authorization(candidates.keys())

    return {
        parcel_id: candidate
        for parcel_id, candidate in candidates.items()
        if parcel_id not in excluded
        and len(candidate.objects) >= criteria.min_objects_count
    }


@dataclass
class _ParcelInfo:
    id_parcellaire: str
    prefix: str
    section: str
    num_parcel: int
    commune_id: Optional[int]
    commune_name: Optional[str]


def _parcel_infos(parcel_ids) -> Dict[int, _ParcelInfo]:
    parcel_ids = list(parcel_ids)
    infos = {}
    for start in range(0, len(parcel_ids), 10000):
        for row in Parcel.objects.filter(
            id__in=parcel_ids[start : start + 10000]
        ).values_list(
            "id",
            "id_parcellaire",
            "prefix",
            "section",
            "num_parcel",
            "commune_id",
            "commune__name",
        ):
            infos[row[0]] = _ParcelInfo(*row[1:])
    return infos


def _eligible_parcels(
    user: User,
    user_group: UserGroup,
    criteria: EligibilityCriteria,
    control_plan: ControlPlan,
    ranked_draft_id: Optional[int] = None,
) -> Tuple[Dict[int, _ParcelCandidate], Dict[int, _ParcelInfo]]:
    """The parcels a wave computed now ranks, shared by the proposal and its live count."""
    candidates = _collect_candidates(
        user, user_group, criteria, control_plan, ranked_draft_id=ranked_draft_id
    )
    infos = _parcel_infos(candidates.keys())
    return {
        parcel_id: candidate
        for parcel_id, candidate in candidates.items()
        if parcel_id in infos
    }, infos


@contextmanager
def _proposal_statement_timeout():
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET LOCAL statement_timeout = %s",
                    [PROPOSAL_STATEMENT_TIMEOUT_MS],
                )
            yield
    except OperationalError as error:
        if "statement timeout" in str(error):
            raise ProposalTimeout()
        raise


def _rank(
    candidates: Dict[int, _ParcelCandidate],
    infos: Dict[int, _ParcelInfo],
    criteria: EligibilityCriteria,
) -> List[_ParcelCandidate]:
    """Lexicographic: the first criterion decides, the next ones break its ties."""

    def key(candidate: _ParcelCandidate):
        values = []
        for criterion in criteria.ranking_criteria:
            if criterion == ControlPlanRankingCriterion.OBJECTS_COUNT:
                values.append(-len(candidate.objects))
            elif criterion == ControlPlanRankingCriterion.NEW_OBJECTS_COUNT:
                values.append(-candidate.new_objects_count)

        info = infos[candidate.parcel_id]
        # the cadastral order breaks the remaining ties, the id makes it total
        values.extend(
            [
                (info.commune_name or "").lower(),
                info.section,
                info.prefix,
                info.num_parcel,
                candidate.parcel_id,
            ]
        )
        return values

    return sorted(candidates.values(), key=key)


def _zone_group_names(zone_groups: List[List[int]]) -> List[str]:
    zones = {
        zone.id: zone
        for zone in GeoCustomZone.objects.filter(
            id__in=[zone_id for group in zone_groups for zone_id in group]
        ).select_related("geo_custom_zone_category")
    }

    names = []
    for group in zone_groups:
        zone = zones.get(group[0]) if group else None
        if zone is None:
            names.append("")
        elif zone.geo_custom_zone_category:
            names.append(zone.geo_custom_zone_category.name)
        else:
            names.append(zone.name)
    return names


def _summary(
    candidate: _ParcelCandidate,
    object_types: Dict[int, ObjectType],
    zone_group_names: List[str],
) -> dict:
    counts = Counter(obj.object_type_id for obj in candidate.objects.values())
    return {
        "zone_names": [
            zone_group_names[index] for index in sorted(candidate.zone_groups)
        ],
        "object_types": [
            {
                "uuid": str(object_types[object_type_id].uuid),
                "name": object_types[object_type_id].name,
                "color": object_types[object_type_id].color,
                "count": count,
            }
            for object_type_id, count in sorted(
                counts.items(),
                key=lambda item: (-item[1], object_types[item[0]].name),
            )
        ],
        "detection_object_uuids": [obj.uuid for obj in candidate.objects.values()][
            :MAX_DETECTION_OBJECT_UUIDS
        ],
    }


def _object_types_of(candidates) -> Dict[int, ObjectType]:
    type_ids = {
        obj.object_type_id
        for candidate in candidates
        for obj in candidate.objects.values()
    }
    return {
        object_type.id: object_type
        for object_type in ObjectType.objects.filter(id__in=type_ids)
    }


def _apply_candidate(
    row: ControlPlanParcel,
    candidate: _ParcelCandidate,
    object_types: Dict[int, ObjectType],
    zone_group_names: List[str],
) -> None:
    row.objects_count = len(candidate.objects)
    row.new_objects_count = candidate.new_objects_count
    row.unverified_objects_count = candidate.unverified_objects_count
    row.summary = _summary(candidate, object_types, zone_group_names)


# Every write locks in the same order, plan then wave then rows, so two of them never
# deadlock: one plan lock serializes all the writes of a plan.


def _split_proposals(
    wave: ControlPlanWave, queryset: Optional[QuerySet] = None
) -> Tuple[QuerySet, QuerySet]:
    """The proposed parcels of a draft and its waiting list: the first ones of the ranking,
    as many as asked, plus those an agent pulled from the waiting list on top of them."""
    proposals = (ControlPlanParcel.objects if queryset is None else queryset).filter(
        wave=wave, control_plan_parcel_status=ControlPlanParcelStatus.PROPOSED
    )
    ranks = list(
        proposals.filter(added_by_agent=False)
        .order_by("rank")
        .values_list("rank", flat=True)[wave.parcels_count - 1 : wave.parcels_count]
    )
    if not ranks:
        # fewer proposals than asked: all are proposed, none waits
        return proposals, proposals.none()

    return (
        proposals.filter(Q(added_by_agent=True) | Q(rank__lte=ranks[0])),
        proposals.filter(added_by_agent=False, rank__gt=ranks[0]),
    )


def _lock_active_plan(control_plan_id: int) -> ControlPlan:
    control_plan = (
        ControlPlan.objects.select_for_update(of=("self",))
        .select_related("user_group")
        .get(pk=control_plan_id)
    )
    if control_plan.control_plan_status != ControlPlanStatus.ACTIVE:
        raise Conflict(CLOSED_PLAN_MESSAGE)
    return control_plan


def _lock_draft_wave(wave_id: int) -> ControlPlanWave:
    control_plan_id = (
        ControlPlanWave.objects.filter(pk=wave_id)
        .values_list("control_plan_id", flat=True)
        .first()
    )
    if control_plan_id is None:
        raise Conflict(DROPPED_DRAFT_MESSAGE)
    control_plan = _lock_active_plan(control_plan_id)

    wave = ControlPlanWave.objects.select_for_update().filter(pk=wave_id).first()
    if wave is None:
        # dropped while this request waited for the lock
        raise Conflict(DROPPED_DRAFT_MESSAGE)
    if wave.control_plan_wave_status != ControlPlanWaveStatus.DRAFT:
        raise Conflict(NOT_A_DRAFT_MESSAGE)
    wave.control_plan = control_plan
    return wave


class ControlPlanWaveService:
    @staticmethod
    def create(
        control_plan: ControlPlan,
        criteria: dict,
        parcels_count: int,
        user: User,
        request_scoped_user_group: Optional[UserGroup] = None,
    ) -> ControlPlanWave:
        with transaction.atomic():
            control_plan = _lock_active_plan(control_plan.pk)
            if control_plan.waves.filter(
                control_plan_wave_status=ControlPlanWaveStatus.DRAFT
            ).exists():
                raise Conflict(
                    "Une proposition est déjà en préparation pour ce plan de contrôle"
                )

            number = (
                control_plan.waves.aggregate(number=Max("number"))["number"] or 0
            ) + 1
            wave = ControlPlanWave.objects.create(
                control_plan=control_plan,
                number=number,
                criteria=criteria,
                parcels_count=parcels_count,
                created_by=user,
            )
            ControlPlanWaveService._compute(wave, user, request_scoped_user_group)

        return wave

    @staticmethod
    def update(
        wave: ControlPlanWave,
        user: User,
        request_scoped_user_group: Optional[UserGroup] = None,
        criteria: Optional[dict] = None,
        parcels_count: Optional[int] = None,
    ) -> ControlPlanWave:
        with transaction.atomic():
            wave = _lock_draft_wave(wave.pk)
            if criteria is not None:
                wave.criteria = criteria
            if parcels_count is not None:
                wave.parcels_count = parcels_count
            wave.save()
            ControlPlanWaveService._compute(wave, user, request_scoped_user_group)

        return wave

    @staticmethod
    def delete_draft(wave: ControlPlanWave) -> None:
        with transaction.atomic():
            wave = _lock_draft_wave(wave.pk)
            ControlPlanWaveService._drop_draft(wave)

    @staticmethod
    def _drop_draft(wave: ControlPlanWave) -> None:
        ControlPlanParcel.objects.filter(
            wave=wave, control_plan_parcel_status=ControlPlanParcelStatus.PROPOSED
        ).delete()
        # its exclusions stay with the plan (wave SET_NULL)
        wave.delete()

    @staticmethod
    def _compute(
        wave: ControlPlanWave,
        user: User,
        request_scoped_user_group: Optional[UserGroup],
    ) -> None:
        """Ranks every eligible parcel and stores the first ones as the proposal: as many as
        asked, plus a waiting list that refills the proposal when a parcel is excluded.

        The parcels excluded from this draft are ranked with them, so a restored one comes
        back at its place in this computation; those no longer eligible go last."""
        control_plan = wave.control_plan
        user_group = control_plan.user_group
        criteria = resolve_criteria(
            wave.criteria, user, request_scoped_user_group, user_group
        )

        with _proposal_statement_timeout():
            proposals = ControlPlanParcel.objects.filter(
                wave=wave,
                control_plan_parcel_status=ControlPlanParcelStatus.PROPOSED,
            )
            added_parcel_ids = set(
                proposals.filter(added_by_agent=True).values_list(
                    "parcel_id", flat=True
                )
            )
            proposals.delete()

            excluded_rows = list(
                ControlPlanParcel.objects.filter(
                    wave=wave,
                    control_plan_parcel_status=ControlPlanParcelStatus.EXCLUDED,
                )
            )
            excluded_by_parcel = {
                row.parcel_id: row for row in excluded_rows if row.parcel_id
            }

            candidates, infos = _eligible_parcels(
                user, user_group, criteria, control_plan, ranked_draft_id=wave.id
            )
            ranked = _rank(candidates, infos, criteria)
            proposable = [
                candidate
                for candidate in ranked
                if candidate.parcel_id not in excluded_by_parcel
            ]
            stored_ids = {
                candidate.parcel_id
                for candidate in proposable[
                    : wave.parcels_count
                    + max(wave.parcels_count, MIN_WAITING_LIST_SIZE)
                ]
            }
            # the parcels an agent added stay added while eligible, unless the ranking
            # now proposes them anyway
            ranked_in_ids = {
                candidate.parcel_id for candidate in proposable[: wave.parcels_count]
            }
            still_added_ids = {
                candidate.parcel_id
                for candidate in proposable
                if candidate.parcel_id in added_parcel_ids
                and candidate.parcel_id not in ranked_in_ids
            }
            stored_ids |= still_added_ids

            object_types = _object_types_of(
                candidate
                for candidate in ranked
                if candidate.parcel_id in stored_ids
                or candidate.parcel_id in excluded_by_parcel
            )
            zone_group_names = _zone_group_names(criteria.zone_groups)
            rows = []
            reranked = set()
            for index, candidate in enumerate(ranked):
                excluded_row = excluded_by_parcel.get(candidate.parcel_id)
                if excluded_row is not None:
                    row = excluded_row
                    reranked.add(row.pk)
                elif candidate.parcel_id in stored_ids:
                    info = infos[candidate.parcel_id]
                    row = ControlPlanParcel(
                        control_plan=control_plan,
                        wave=wave,
                        parcel_id=candidate.parcel_id,
                        id_parcellaire=info.id_parcellaire,
                        prefix=info.prefix,
                        section=info.section,
                        num_parcel=info.num_parcel,
                        commune_id=info.commune_id,
                        control_plan_parcel_status=ControlPlanParcelStatus.PROPOSED,
                        added_by_agent=candidate.parcel_id in still_added_ids,
                    )
                    rows.append(row)
                else:
                    continue
                row.rank = index + 1
                _apply_candidate(row, candidate, object_types, zone_group_names)

            no_longer_eligible = [
                row for row in excluded_rows if row.pk not in reranked
            ]
            for offset, row in enumerate(no_longer_eligible):
                row.rank = len(ranked) + offset + 1

            ControlPlanParcel.objects.bulk_create(rows, batch_size=1000)
            ControlPlanParcel.objects.bulk_update(
                excluded_rows,
                [
                    "rank",
                    "objects_count",
                    "new_objects_count",
                    "unverified_objects_count",
                    "summary",
                ],
                batch_size=500,
            )

            wave.eligible_parcels_count = len(proposable)
            wave.computed_at = timezone.now()
            wave.save(
                update_fields=[
                    "eligible_parcels_count",
                    "computed_at",
                    "updated_at",
                ]
            )

    @staticmethod
    def eligible_count(
        control_plan: ControlPlan,
        criteria: dict,
        user: User,
        request_scoped_user_group: Optional[UserGroup] = None,
    ) -> dict:
        """What a wave computed now with these criteria would find eligible. Stores
        nothing: the draft's proposed rows, which a recompute replaces, take no parcel."""
        if control_plan.control_plan_status != ControlPlanStatus.ACTIVE:
            raise Conflict(CLOSED_PLAN_MESSAGE)

        user_group = control_plan.user_group
        resolved = resolve_criteria(
            criteria, user, request_scoped_user_group, user_group
        )
        with _proposal_statement_timeout():
            candidates, _ = _eligible_parcels(user, user_group, resolved, control_plan)

        return {
            "eligible_parcels_count": len(candidates),
            "eligible_objects_count": sum(
                len(candidate.objects) for candidate in candidates.values()
            ),
        }

    @staticmethod
    def proposal_summary(wave: ControlPlanWave) -> dict:
        excluded_count = ControlPlanParcel.objects.filter(
            control_plan_id=wave.control_plan_id,
            control_plan_parcel_status=ControlPlanParcelStatus.EXCLUDED,
        ).count()

        if wave.control_plan_wave_status == ControlPlanWaveStatus.VALIDATED:
            rows = list(
                ControlPlanParcel.objects.filter(
                    wave=wave,
                    control_plan_parcel_status__in=[
                        ControlPlanParcelStatus.PLANNED,
                        ControlPlanParcelStatus.REMOVED,
                    ],
                ).values_list("objects_count", "unverified_objects_count")
            )
            waiting_count = 0
            added_count = 0
        else:
            proposed, waiting = _split_proposals(wave)
            rows = list(
                proposed.values_list("objects_count", "unverified_objects_count")
            )
            waiting_count = waiting.count()
            added_count = proposed.filter(added_by_agent=True).count()

        return {
            "proposed_count": len(rows),
            "waiting_count": waiting_count,
            "added_count": added_count,
            "excluded_count": excluded_count,
            "objects_count": sum(objects for objects, _ in rows),
            "unverified_objects_count": sum(unverified for _, unverified in rows),
        }

    @staticmethod
    def validate(
        wave: ControlPlanWave,
        user: User,
        request_scoped_user_group: Optional[UserGroup] = None,
    ) -> dict:
        """Sets the eligible objects of the proposed parcels « À contrôler ». Objects the
        caller may not edit are left out; a parcel left with none is skipped."""
        with transaction.atomic():
            wave = _lock_draft_wave(wave.pk)
            control_plan = wave.control_plan
            user_group = control_plan.user_group

            proposed, _ = _split_proposals(wave)
            selected = list(
                proposed.annotate(commune_name=F("commune__name")).order_by("rank")
            )
            criteria = resolve_criteria(
                wave.criteria, user, request_scoped_user_group, user_group
            )
            # the proposal may be days old: what is eligible now decides
            candidates = _collect_candidates(
                user,
                user_group,
                criteria,
                control_plan,
                parcel_ids=[row.parcel_id for row in selected if row.parcel_id],
            )

            detection_data_ids = [
                obj.detection_data_id
                for candidate in candidates.values()
                for obj in candidate.objects.values()
            ]
            # Locked, then read again: an agent may have controlled one of them meanwhile,
            # or another group's plan taken it.
            detection_datas = {
                detection_data.id: detection_data
                for detection_data in DetectionData.objects.select_for_update()
                .filter(id__in=detection_data_ids)
                .order_by("id")
            }
            not_controlled_ids = [
                detection_data_id
                for detection_data_id, detection_data in detection_datas.items()
                if detection_data.detection_control_status
                == DetectionControlStatus.NOT_CONTROLLED
            ]
            switchable_ids = set(
                DetectionPermission(
                    user=user, scoped_user_group=request_scoped_user_group
                )
                .writable_detections(
                    Detection.objects.filter(detection_data_id__in=not_controlled_ids)
                )
                .values_list("detection_data_id", flat=True)
            )

            now = timezone.now()
            object_types = _object_types_of(candidates.values())
            zone_group_names = _zone_group_names(criteria.zone_groups)
            detection_datas_to_update = []
            plan_objects = []
            planned = []
            skipped = []

            for row in selected:
                candidate = candidates.get(row.parcel_id)
                if candidate is not None:
                    candidate.objects = {
                        object_id: obj
                        for object_id, obj in candidate.objects.items()
                        if obj.detection_data_id in switchable_ids
                    }
                if candidate is None or not candidate.objects:
                    skipped.append(row)
                    continue

                for object_id, obj in candidate.objects.items():
                    detection_data = detection_datas[obj.detection_data_id]
                    plan_objects.append(
                        ControlPlanParcelObject(
                            control_plan_parcel=row,
                            detection_object_id=object_id,
                            previous_validation_status=detection_data.detection_validation_status,
                        )
                    )
                    detection_data.set_detection_control_status(
                        DetectionControlStatus.TO_CONTROL
                    )
                    detection_data.user_last_update = user
                    detection_data.updated_at = now
                    detection_datas_to_update.append(detection_data)

                _apply_candidate(row, candidate, object_types, zone_group_names)
                row.control_plan_parcel_status = ControlPlanParcelStatus.PLANNED
                row.status_changed_by = user
                row.status_changed_at = now
                row.updated_at = now
                planned.append(row)

            if not planned:
                # rolled back: the draft stays, to be recomputed
                raise Conflict(
                    "Plus aucune parcelle de la proposition ne peut passer à contrôler : modifiez les critères pour la recalculer"
                )

            bulk_update_with_history(
                detection_datas_to_update,
                DetectionData,
                DETECTION_DATA_SWITCHED_FIELDS,
                batch_size=500,
                default_user=user,
                default_change_reason=CONTROL_PLAN_HISTORY_CHANGE_REASON,
            )
            ControlPlanParcel.objects.bulk_update(
                planned,
                [
                    "control_plan_parcel_status",
                    "status_changed_by",
                    "status_changed_at",
                    "objects_count",
                    "new_objects_count",
                    "unverified_objects_count",
                    "summary",
                    "updated_at",
                ],
                batch_size=500,
            )
            ControlPlanParcelObject.objects.bulk_create(plan_objects, batch_size=1000)
            # the skipped parcels and the waiting list: proposable again by a next wave
            ControlPlanParcel.objects.filter(
                wave=wave, control_plan_parcel_status=ControlPlanParcelStatus.PROPOSED
            ).delete()

            wave.control_plan_wave_status = ControlPlanWaveStatus.VALIDATED
            wave.validated_by = user
            wave.validated_at = now
            wave.save()
            _invalidate_counts_on_commit()

        return {
            "planned_parcels_count": len(planned),
            "switched_objects_count": len(detection_datas_to_update),
            "skipped_parcels": [
                {
                    "id_parcellaire": row.id_parcellaire,
                    "commune_name": row.commune_name,
                }
                for row in skipped
            ],
        }


# ----------------------------------------------------------------------- plan parcels


class ControlPlanParcelService:
    @staticmethod
    def list_section(
        control_plan: ControlPlan,
        section: str,
        follow_up_status: Optional[str] = None,
    ) -> QuerySet[ControlPlanParcel]:
        queryset = (
            ControlPlanParcel.objects.filter(control_plan=control_plan)
            .select_related("wave", "commune", "parcel")
            .defer("commune__geometry", "parcel__geometry")
        )

        if section in (
            ControlPlanParcelSection.PROPOSED,
            ControlPlanParcelSection.WAITING,
        ):
            draft = control_plan.waves.filter(
                control_plan_wave_status=ControlPlanWaveStatus.DRAFT
            ).first()
            if draft is None:
                return queryset.none()

            proposed, waiting = _split_proposals(draft, queryset)
            return (
                proposed if section == ControlPlanParcelSection.PROPOSED else waiting
            ).order_by("rank")

        if section == ControlPlanParcelSection.PLANNED:
            queryset = queryset.filter(
                control_plan_parcel_status=ControlPlanParcelStatus.PLANNED
            ).annotate(**follow_up_annotations())
            if follow_up_status == ControlPlanFollowUpStatus.TO_CONTROL:
                queryset = queryset.filter(has_to_control=True)
            elif follow_up_status == ControlPlanFollowUpStatus.CONTROLLED:
                queryset = queryset.filter(has_to_control=False, has_controlled=True)
            elif follow_up_status == ControlPlanFollowUpStatus.RELEASED:
                queryset = queryset.filter(has_to_control=False, has_controlled=False)
            return queryset.order_by("wave__number", "rank")

        return queryset.filter(control_plan_parcel_status=section).order_by(
            "-status_changed_at", "rank"
        )

    @staticmethod
    def follow_up_status(plan_parcel: ControlPlanParcel) -> Optional[str]:
        if plan_parcel.control_plan_parcel_status != ControlPlanParcelStatus.PLANNED:
            return None
        if not hasattr(plan_parcel, "has_to_control"):
            plan_parcel = (
                ControlPlanParcel.objects.filter(pk=plan_parcel.pk)
                .annotate(**follow_up_annotations())
                .get()
            )
        if plan_parcel.has_to_control:
            return ControlPlanFollowUpStatus.TO_CONTROL
        if plan_parcel.has_controlled:
            return ControlPlanFollowUpStatus.CONTROLLED
        return ControlPlanFollowUpStatus.RELEASED

    @staticmethod
    def exclude(plan_parcel: ControlPlanParcel, user: User) -> ControlPlanParcel:
        with transaction.atomic():
            if plan_parcel.wave_id is None:
                raise Conflict("Seule une parcelle proposée peut être écartée")
            _lock_draft_wave(plan_parcel.wave_id)
            plan_parcel = ControlPlanParcel.objects.select_for_update().get(
                pk=plan_parcel.pk
            )
            if (
                plan_parcel.control_plan_parcel_status
                != ControlPlanParcelStatus.PROPOSED
            ):
                raise Conflict("Seule une parcelle proposée peut être écartée")

            plan_parcel.control_plan_parcel_status = ControlPlanParcelStatus.EXCLUDED
            # restored, it goes back to its rank
            plan_parcel.added_by_agent = False
            plan_parcel.status_changed_by = user
            plan_parcel.status_changed_at = timezone.now()
            plan_parcel.save()

        return plan_parcel

    @staticmethod
    def _lock_proposal_row(plan_parcel: ControlPlanParcel, message: str):
        if plan_parcel.wave_id is None:
            raise Conflict(message)
        wave = _lock_draft_wave(plan_parcel.wave_id)
        return wave, ControlPlanParcel.objects.select_for_update().get(
            pk=plan_parcel.pk
        )

    @staticmethod
    def include(plan_parcel: ControlPlanParcel) -> ControlPlanParcel:
        """Pulls a parcel of the waiting list into the proposal, on top of the count asked."""
        message = "Seule une parcelle de la liste d'attente peut être ajoutée au plan"
        with transaction.atomic():
            wave, plan_parcel = ControlPlanParcelService._lock_proposal_row(
                plan_parcel, message
            )
            _, waiting = _split_proposals(wave)
            if not waiting.filter(pk=plan_parcel.pk).exists():
                raise Conflict(message)

            plan_parcel.added_by_agent = True
            plan_parcel.save(update_fields=["added_by_agent", "updated_at"])

        return plan_parcel

    @staticmethod
    def put_back(plan_parcel: ControlPlanParcel) -> ControlPlanParcel:
        """Undoes `include`: the parcel goes back to its rank."""
        message = "Seule une parcelle ajoutée au plan peut être remise en attente"
        with transaction.atomic():
            _, plan_parcel = ControlPlanParcelService._lock_proposal_row(
                plan_parcel, message
            )
            if (
                plan_parcel.control_plan_parcel_status
                != ControlPlanParcelStatus.PROPOSED
                or not plan_parcel.added_by_agent
            ):
                raise Conflict(message)

            plan_parcel.added_by_agent = False
            plan_parcel.save(update_fields=["added_by_agent", "updated_at"])

        return plan_parcel

    @staticmethod
    def restore(plan_parcel: ControlPlanParcel, user: User) -> None:
        """An excluded parcel goes back to the draft at its rank; otherwise (excluded by an
        earlier wave, or removed) the plan forgets it, so a next wave may propose it."""
        with transaction.atomic():
            control_plan = _lock_active_plan(plan_parcel.control_plan_id)
            draft = control_plan.waves.filter(
                control_plan_wave_status=ControlPlanWaveStatus.DRAFT
            ).first()

            plan_parcel = ControlPlanParcel.objects.select_for_update().get(
                pk=plan_parcel.pk
            )
            if plan_parcel.control_plan_parcel_status not in (
                ControlPlanParcelStatus.EXCLUDED,
                ControlPlanParcelStatus.REMOVED,
            ):
                raise Conflict(
                    "Seule une parcelle écartée ou retirée peut être réintégrée"
                )

            if (
                plan_parcel.control_plan_parcel_status
                == ControlPlanParcelStatus.EXCLUDED
                and draft is not None
                and plan_parcel.wave_id == draft.id
            ):
                plan_parcel.control_plan_parcel_status = (
                    ControlPlanParcelStatus.PROPOSED
                )
                plan_parcel.status_changed_by = user
                plan_parcel.status_changed_at = timezone.now()
                plan_parcel.save()
                return

            plan_parcel.delete()

    @staticmethod
    def remove(
        plan_parcel: ControlPlanParcel,
        user: User,
        request_scoped_user_group: Optional[UserGroup] = None,
    ) -> ControlPlanParcel:
        """Undoes what the plan did on the parcel: its objects still « À contrôler » go back
        to « Non contrôlé », and to « Non vérifié » when the plan had promoted them."""
        with transaction.atomic():
            # a closed plan leaves its statuses as they are
            _lock_active_plan(plan_parcel.control_plan_id)
            plan_parcel = ControlPlanParcel.objects.select_for_update().get(
                pk=plan_parcel.pk
            )
            if (
                plan_parcel.control_plan_parcel_status
                != ControlPlanParcelStatus.PLANNED
            ):
                raise Conflict("Seule une parcelle du plan peut en être retirée")

            plan_objects = {
                plan_object.detection_object_id: plan_object
                for plan_object in plan_parcel.control_plan_parcel_objects.all()
            }
            # left alone when another active plan holds it now
            claimed_elsewhere = set(
                ControlPlanParcelObject.objects.filter(
                    detection_object_id__in=plan_objects.keys(),
                    control_plan_parcel__control_plan_parcel_status=ControlPlanParcelStatus.PLANNED,
                    control_plan_parcel__control_plan__control_plan_status=ControlPlanStatus.ACTIVE,
                    control_plan_parcel__control_plan__deleted=False,
                )
                .exclude(control_plan_parcel=plan_parcel)
                .values_list("detection_object_id", flat=True)
            )
            # the current detection: after a new imagery import it is a newer row that
            # inherited « À contrôler »
            detections = list(
                current_detections().filter(
                    detection_object_id__in=[
                        object_id
                        for object_id in plan_objects
                        if object_id not in claimed_elsewhere
                    ]
                )
            )
            detection_datas = {
                detection_data.id: detection_data
                for detection_data in DetectionData.objects.select_for_update()
                .filter(
                    id__in=[detection.detection_data_id for detection in detections]
                )
                .order_by("id")
            }

            now = timezone.now()
            detections_to_check = []
            detection_datas_to_update = []
            for detection in detections:
                detection_data = detection_datas.get(detection.detection_data_id)
                if (
                    detection_data is None
                    or detection_data.detection_control_status
                    != DetectionControlStatus.TO_CONTROL
                ):
                    continue

                detection_data.set_detection_control_status(
                    DetectionControlStatus.NOT_CONTROLLED
                )
                previous = plan_objects[
                    detection.detection_object_id
                ].previous_validation_status
                if (
                    previous == DetectionValidationStatus.DETECTED_NOT_VERIFIED
                    and detection_data.detection_validation_status
                    == DetectionValidationStatus.SUSPECT
                ):
                    detection_data.detection_validation_status = (
                        DetectionValidationStatus.DETECTED_NOT_VERIFIED
                    )
                detection_data.user_last_update = user
                detection_data.updated_at = now
                detections_to_check.append(detection)
                detection_datas_to_update.append(detection_data)

            if detections_to_check:
                DetectionPermission(
                    user=user, scoped_user_group=request_scoped_user_group
                ).validate_detections_edit_permission(detections=detections_to_check)
                bulk_update_with_history(
                    detection_datas_to_update,
                    DetectionData,
                    DETECTION_DATA_SWITCHED_FIELDS,
                    batch_size=500,
                    default_user=user,
                    default_change_reason=CONTROL_PLAN_HISTORY_CHANGE_REASON,
                )

            plan_parcel.control_plan_parcel_status = ControlPlanParcelStatus.REMOVED
            plan_parcel.status_changed_by = user
            plan_parcel.status_changed_at = now
            plan_parcel.save()
            _invalidate_counts_on_commit()

        return plan_parcel

    @staticmethod
    def preview(plan_parcel: ControlPlanParcel, user: User) -> dict:
        """The parcel and its objects on the imagery, as the group sees them: each year
        shows the objects as detected on it, not today's outlines."""
        from core.permissions.tile_set import TileSetPermission
        from core.serializers.tile_set import TileSetMinimalSerializer

        empty = {
            "parcel_geometry": None,
            "bounds": None,
            "detection_objects": [],
            "tile_set_previews": [],
        }
        if plan_parcel.parcel_id is None:
            return empty

        user_group = plan_parcel.control_plan.user_group
        parcel_geometry = (
            Parcel.objects.filter(id=plan_parcel.parcel_id)
            .values_list("geometry", flat=True)
            .first()
        )
        if parcel_geometry is None:
            return empty

        current = [
            detection
            for detection in visible_current_detections(user, user_group)
            .filter(detection_object__parcel_id=plan_parcel.parcel_id)
            .select_related("detection_object__object_type", "detection_data")
            .order_by("id")
            if detection.detection_data is not None
        ]
        tile_set_previews = TileSetPermission(
            user=user, scoped_user_group=user_group
        ).get_previews(filter_tile_set_intersects_geometry=parcel_geometry)

        shown_tile_set_ids = [
            preview["tile_set"].id
            for preview in tile_set_previews
            if preview["preview"]
        ]
        detections_by_tile_set = defaultdict(list)
        for detection in (
            Detection.objects.filter(
                detection_object_id__in=[
                    detection.detection_object_id for detection in current
                ],
                tile_set_id__in=shown_tile_set_ids,
            )
            .select_related("detection_object__object_type")
            .order_by("id")
        ):
            detections_by_tile_set[detection.tile_set_id].append(detection)

        geometries = [parcel_geometry] + [
            detection.geometry
            for detections in detections_by_tile_set.values()
            for detection in detections
        ]

        def serialize_object(detection: Detection) -> dict:
            return {
                "uuid": str(detection.detection_object.uuid),
                "object_type_name": detection.detection_object.object_type.name,
                "object_type_color": detection.detection_object.object_type.color,
                "geometry": json.loads(detection.geometry.geojson),
            }

        return {
            "parcel_geometry": json.loads(parcel_geometry.geojson),
            "bounds": list(
                GeometryCollection(*geometries, srid=parcel_geometry.srid).extent
            ),
            "detection_objects": [
                {
                    **serialize_object(detection),
                    "detection_control_status": detection.detection_data.detection_control_status,
                    "detection_validation_status": detection.detection_data.detection_validation_status,
                }
                for detection in current
            ],
            "tile_set_previews": [
                {
                    "tile_set": TileSetMinimalSerializer(preview["tile_set"]).data,
                    "preview": preview["preview"],
                    "detection_objects": [
                        serialize_object(detection)
                        for detection in detections_by_tile_set[preview["tile_set"].id]
                    ],
                }
                for preview in tile_set_previews
            ],
        }


# ----------------------------------------------------------------------- plans


class ControlPlanService:
    @staticmethod
    def create(
        user_group: UserGroup, name: str, start_date, end_date, user: User
    ) -> ControlPlan:
        # a wave needs at least one: the plan could never be computed
        if not group_zones(user_group).exists():
            raise ValidationError(
                {
                    "user_group_uuid": [
                        "Ce groupe n'a aucune zone à enjeux active : un plan de contrôle en a besoin"
                    ]
                }
            )

        conflict = Conflict(
            "Ce groupe a déjà un plan de contrôle en cours : clôturez-le avant d'en créer un autre"
        )
        if ControlPlan.objects.filter(
            user_group=user_group,
            control_plan_status=ControlPlanStatus.ACTIVE,
            deleted=False,
        ).exists():
            raise conflict

        try:
            with transaction.atomic():
                return ControlPlan.objects.create(
                    user_group=user_group,
                    name=name,
                    start_date=start_date,
                    end_date=end_date,
                    created_by=user,
                )
        except IntegrityError:
            # another member created one meanwhile
            raise conflict

    @staticmethod
    def update(control_plan: ControlPlan, **fields) -> ControlPlan:
        if control_plan.control_plan_status != ControlPlanStatus.ACTIVE:
            raise Conflict(CLOSED_PLAN_MESSAGE)
        for name, value in fields.items():
            setattr(control_plan, name, value)
        control_plan.save()
        return control_plan

    @staticmethod
    def close(control_plan: ControlPlan, user: User) -> ControlPlan:
        """Statuses are left as they are: what is still « À contrôler » shows outside the
        next plan."""
        with transaction.atomic():
            control_plan = _lock_active_plan(control_plan.pk)
            for draft in control_plan.waves.filter(
                control_plan_wave_status=ControlPlanWaveStatus.DRAFT
            ):
                ControlPlanWaveService._drop_draft(draft)

            control_plan.control_plan_status = ControlPlanStatus.CLOSED
            control_plan.closed_by = user
            control_plan.closed_at = timezone.now()
            control_plan.save()
            _invalidate_counts_on_commit()

        return control_plan

    @staticmethod
    def delete(control_plan: ControlPlan) -> None:
        with transaction.atomic():
            control_plan = ControlPlan.objects.select_for_update(of=("self",)).get(
                pk=control_plan.pk
            )
            if control_plan.waves.filter(
                control_plan_wave_status=ControlPlanWaveStatus.VALIDATED
            ).exists():
                raise Conflict(
                    "Des parcelles de ce plan sont déjà à contrôler : clôturez-le plutôt que de le supprimer"
                )

            for draft in control_plan.waves.filter(
                control_plan_wave_status=ControlPlanWaveStatus.DRAFT
            ):
                ControlPlanWaveService._drop_draft(draft)

            control_plan.deleted = True
            control_plan.deleted_at = timezone.now()
            control_plan.save()
            _invalidate_counts_on_commit()

    @staticmethod
    def counters(control_plan: ControlPlan) -> dict:
        follow_ups = list(
            ControlPlanParcel.objects.filter(
                control_plan=control_plan,
                control_plan_parcel_status=ControlPlanParcelStatus.PLANNED,
            )
            .annotate(**follow_up_annotations())
            .values_list("has_to_control", "has_controlled")
        )
        to_control = sum(1 for has_to_control, _ in follow_ups if has_to_control)
        controlled = sum(
            1
            for has_to_control, has_controlled in follow_ups
            if not has_to_control and has_controlled
        )
        by_status = dict(
            ControlPlanParcel.objects.filter(control_plan=control_plan)
            .values("control_plan_parcel_status")
            .annotate(count=Count("id"))
            .values_list("control_plan_parcel_status", "count")
        )

        return {
            "planned": len(follow_ups),
            "to_control": to_control,
            "controlled": controlled,
            "released": len(follow_ups) - to_control - controlled,
            "removed": by_status.get(ControlPlanParcelStatus.REMOVED, 0),
            "excluded": by_status.get(ControlPlanParcelStatus.EXCLUDED, 0),
        }

    @staticmethod
    def groups(permission: ControlPlanPermission) -> List[dict]:
        user_groups = list(permission.accessible_groups().order_by("name"))
        active_plans = dict(
            ControlPlan.objects.filter(
                user_group__in=user_groups,
                control_plan_status=ControlPlanStatus.ACTIVE,
                deleted=False,
            ).values_list("user_group_id", "uuid")
        )

        return [
            {
                "uuid": user_group.uuid,
                "name": user_group.name,
                "user_group_type": user_group.user_group_type,
                "can_edit": permission.can_edit(user_group),
                "active_control_plan_uuid": active_plans.get(user_group.id),
            }
            for user_group in user_groups
        ]

    @staticmethod
    def prerequisites(
        user: User,
        request_scoped_user_group: Optional[UserGroup],
        user_group: UserGroup,
    ) -> dict:
        """What the « nettoyage » left: objects still « Non vérifié », and objects with no
        cadastral parcel (a plan is made of parcels). Defaults of the map filters."""
        detections = visible_current_detections(user, user_group).filter(
            detection_object__object_type__in=[
                object_type
                for object_type, _ in plan_object_types(
                    user, request_scoped_user_group, user_group
                )
            ],
            detection_data__detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
        )
        detections = score_at_least(detections, DEFAULT_SCORE_MIN)
        zone_ids = list(group_zones(user_group).values_list("id", flat=True))
        detections = in_zones_or_drawn(detections, zone_ids)
        detections = exclude_prescribed(detections)

        return {
            # a wave needs at least one: told before the criteria step
            "custom_zones_count": len(zone_ids),
            "unverified_objects_count": detections.filter(
                detection_data__detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED
            ).count(),
            "objects_without_parcel_count": detections.filter(
                detection_object__parcel__isnull=True,
                detection_data__detection_validation_status__in=[
                    DetectionValidationStatus.DETECTED_NOT_VERIFIED,
                    DetectionValidationStatus.SUSPECT,
                    DetectionValidationStatus.ILLEGAL,
                ],
            ).count(),
        }

    @staticmethod
    def criteria_options(
        user: User,
        request_scoped_user_group: Optional[UserGroup],
        user_group: UserGroup,
    ) -> dict:
        """The plan group's object types; its zones à enjeux grouped as the map layers
        are (one per category, an uncategorized zone alone)."""
        object_types = [
            {
                "uuid": object_type.uuid,
                "name": object_type.name,
                "color": object_type.color,
                "status": object_type_status,
            }
            for object_type, object_type_status in plan_object_types(
                user, request_scoped_user_group, user_group
            )
        ]

        zone_groups = {}
        for zone in (
            group_zones(user_group)
            .select_related("geo_custom_zone_category")
            .order_by("name")
        ):
            category = zone.geo_custom_zone_category
            key = f"category-{category.uuid}" if category else f"zone-{zone.uuid}"
            zone_group = zone_groups.setdefault(
                key,
                {
                    "key": key,
                    "name": category.name if category else zone.name,
                    "color": category.color if category else zone.color,
                    "custom_zone_uuids": [],
                },
            )
            zone_group["custom_zone_uuids"].append(zone.uuid)

        return {
            "object_types": object_types,
            "custom_zone_groups": sorted(
                zone_groups.values(), key=lambda zone_group: zone_group["name"].lower()
            ),
            "default_perimeter": ControlPlanService.default_perimeter(user_group),
            "single_commune": ControlPlanService.single_commune(user_group),
        }

    @staticmethod
    def single_commune(user_group: UserGroup) -> Optional[dict]:
        """The only commune of a group's territory: its plan has no perimeter to choose."""
        communes = list(
            territory_communes(user_group).values_list("uuid", "name", "iso_code")[:2]
        )
        if len(communes) != 1:
            return None
        uuid, name, code = communes[0]
        return {"uuid": uuid, "name": name, "code": code}

    @staticmethod
    def default_perimeter(user_group: UserGroup) -> dict:
        """The communes and EPCIs a collectivity group is attached to, which prefill the
        perimeter of its first wave. Nothing for a DDTM or a group holding a department or a
        region: its plan starts on the whole territory."""
        perimeter = {"communes": [], "epcis": []}
        if user_group.user_group_type == UserGroupType.DDTM:
            return perimeter

        zones = GeoZone.objects.filter(user_groups=user_group, deleted=False)
        if zones.filter(
            geo_zone_type__in=[GeoZoneType.DEPARTMENT, GeoZoneType.REGION]
        ).exists():
            return perimeter

        zone_ids = zones.values("id")
        perimeter["communes"] = [
            {"uuid": uuid, "name": name, "code": code}
            for uuid, name, code in GeoCommune.objects.filter(id__in=zone_ids)
            .order_by("name")
            .values_list("uuid", "name", "iso_code")
        ]
        perimeter["epcis"] = [
            {"uuid": uuid, "name": name, "code": code}
            for uuid, name, code in GeoEpci.objects.filter(id__in=zone_ids)
            .order_by("name")
            .values_list("uuid", "name", "siren_code")
        ]
        return perimeter

    @staticmethod
    def out_of_plan_parcels(user: User, control_plan: ControlPlan) -> QuerySet[Parcel]:
        """Parcels of the territory holding an object « À contrôler » the plan did not set:
        set by hand, by another group's plan, or left by a closed plan."""
        from core.services.parcel_filter import ParcelFilterService

        user_group = control_plan.user_group
        zone_uuids = [
            str(uuid) for uuid in group_zones(user_group).values_list("uuid", flat=True)
        ]
        if not zone_uuids:
            return Parcel.objects.none()

        queryset = ParcelFilterService(
            user=user, scoped_user_group=user_group
        ).apply_filters(
            queryset=Parcel.objects.all(),
            filter_params={
                "customZonesUuids": ",".join(zone_uuids),
                "interfaceDrawn": "ALL",
                "detectionControlStatuses": DetectionControlStatus.TO_CONTROL,
                "detectionValidationStatuses": ",".join(
                    [
                        DetectionValidationStatus.DETECTED_NOT_VERIFIED,
                        DetectionValidationStatus.SUSPECT,
                        DetectionValidationStatus.ILLEGAL,
                    ]
                ),
            },
            filter_has_detections=True,
            with_details=True,
        )
        planned_parcel_ids = ControlPlanParcel.objects.filter(
            control_plan=control_plan,
            control_plan_parcel_status=ControlPlanParcelStatus.PLANNED,
            parcel_id__isnull=False,
        ).values("parcel_id")

        return (
            queryset.exclude(id__in=planned_parcel_ids)
            .order_by("commune__name", "section", "num_parcel", "id")
            .distinct()
        )
