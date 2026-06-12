import os
from collections import defaultdict
from typing import List, Optional

from django.db.models import Count

from core.models.detection import Detection
from core.models.detection_data import DetectionValidationStatusChangeReason
from core.models.geo_commune import GeoCommune
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_department import GeoDepartment
from core.models.parcel import Parcel
from core.models.tile_set import TileSet
from core.models.user_group import UserGroup, UserUserGroup
from core.utils.cache import get_or_compute, safe_cache_set
from core.utils.string import normalize

# This endpoint aggregates over the whole detection/parcel dataset (tens of millions
# of rows): two full-dataset GROUP BY scans (Detection x DetectionObject by commune,
# and Parcel by commune). Covering indexes let PostgreSQL answer them with index-only
# scans instead of multi-GB heap scans — a cold computation went from ~100s to
# ~10-20s — but that is still far too slow for a request/response cycle, so the
# result is cached and the cache must actually stay warm in normal operation.
#
# Two things the queries below deliberately do to stay on index-only scans (each
# would silently fall back to multi-GB heap scans if undone):
# - they COUNT() the indexed column, never `id` (a column absent from the index
#   forces heap fetches);
# - they do NOT filter on deleted=False: nothing in the app ever soft-deletes these
#   rows, and `deleted` is in no index, so the filter would only force heap access.
#
# Crucially the key is NOT folded with `get_count_cache_version()`. That counter is
# bumped on every single Detection/DetectionData/DetectionObject/Parcel write (see
# core/signals.py) — i.e. on every interactive validation-status edit anywhere in the
# country — which would invalidate this heavy aggregate on essentially every edit and
# force the SUPER_ADMIN dashboard to pay the ~1-2 min cold cost on almost every load
# (the "very long to load" symptom). The deployed-data overview is a slow-moving
# deployment-status figure that tolerates bounded staleness, so it is invalidated only
# by the TTL below (an upper bound on staleness) and refreshed out-of-band by
# `manage.py warm_deployed_data_cache` — run that after a detection/parcel import (and,
# ideally, on a schedule) so HTTP requests always hit a warm cache.
DEPLOYED_DATA_CACHE_TTL = int(os.environ.get("DEPLOYED_DATA_CACHE_TTL", 24 * 60 * 60))


class DeployedDataService:
    """Aggregates "deployed data" statistics per department for the SUPER_ADMIN dashboard.

    A department is considered "deployed" as soon as at least one of its communes
    holds a detection (Detection -> DetectionObject.commune). Departments without any
    detection are excluded from the result.

    User groups, custom zones and tile sets are reported when they are associated
    (through their `geo_zones` M2M) either to the department itself or to any of its
    communes.

    Tile sets are intentionally taken from this geographic association and NOT from
    `Detection.tile_set`: a detection's tile set is merely the imagery layer it was
    drawn/analysed on, which is not geographically scoped — the very same tile set
    appears on detections all over the country — so deriving the "fonds de carte" from
    it yields geographically incoherent results (e.g. a Brittany commune showing tile
    sets named after southern departments).
    """

    @staticmethod
    def get_departments_deployed_data(
        q: Optional[str] = None, min_commune_detections: int = 0
    ) -> List[dict]:
        # The full (unfiltered) dataset is computed once and cached; the `q` search and
        # the per-commune detection threshold are applied in Python so every request
        # hits the cache instead of recomputing.
        departments = DeployedDataService._get_all_departments_cached()
        needle = normalize(q) if q else None

        result = []
        for department in departments:
            if needle and needle not in normalize(department["name"]):
                continue

            department = DeployedDataService._apply_min_commune_detections(
                department, min_commune_detections
            )
            if department is not None:
                result.append(department)

        return result

    @staticmethod
    def get_departments_summary(
        q: Optional[str] = None, min_commune_detections: int = 0
    ) -> List[dict]:
        """Lightweight per-department rows for the list view (no nested detail).

        Carries only what the list table needs (commune count, distinct user count and
        the tile-set years); the full per-department breakdown is served separately by
        `get_department_deployed_data`.
        """
        return [
            DeployedDataService._summarize_department(department)
            for department in DeployedDataService.get_departments_deployed_data(
                q=q, min_commune_detections=min_commune_detections
            )
        ]

    @staticmethod
    def get_department_deployed_data(
        uuid, min_commune_detections: int = 0
    ) -> Optional[dict]:
        """Full deployed-data detail for a single department.

        Returns None when the department is unknown or no longer deployed at the given
        threshold (so the view can answer 404). The threshold mirrors the list so the
        detail's commune count/list stays consistent with the row that was clicked.

        The department is located FIRST and the threshold applied to it alone:
        applying the threshold to the whole dataset before searching (the previous
        implementation) copied and filtered every department's commune list just to
        serve one of them.
        """
        department = next(
            (
                department
                for department in DeployedDataService._get_all_departments_cached()
                if str(department["uuid"]) == str(uuid)
            ),
            None,
        )
        if department is None:
            return None

        return DeployedDataService._apply_min_commune_detections(
            department, min_commune_detections
        )

    @staticmethod
    def _apply_min_commune_detections(
        department: dict, min_commune_detections: int
    ) -> Optional[dict]:
        """Apply the per-commune detection threshold to one cached department dict.

        Returns the department untouched when no threshold is set, a filtered copy
        when some communes qualify (the cached structure is shared and must never be
        mutated), or None when no commune qualifies — the department is no longer
        "deployed" at that threshold.
        """
        if min_commune_detections <= 0:
            return department

        communes = [
            commune
            for commune in department["communes"]
            if commune["detections_count"] >= min_commune_detections
        ]
        if not communes:
            return None

        return {
            **department,
            "communes": communes,
            "communes_with_detections_count": len(communes),
        }

    @staticmethod
    def _summarize_department(department: dict) -> dict:
        user_uuids = {
            user["uuid"]
            for user_group in department["user_groups"]
            for user in user_group["users"]
        }
        years = sorted(
            {tile_set["date"].year for tile_set in department["tile_sets"]},
            reverse=True,
        )
        return {
            "uuid": department["uuid"],
            "name": department["name"],
            "communes_with_detections_count": department[
                "communes_with_detections_count"
            ],
            "users_count": len(user_uuids),
            "tile_set_years": [str(year) for year in years],
        }

    @staticmethod
    def _cache_key() -> str:
        # Deliberately a STABLE key (no count-cache version): the deployed-data overview
        # is invalidated only by its TTL and refreshed out-of-band by
        # `warm_deployed_data_cache` (see the module docstring for why folding in
        # get_count_cache_version() defeated the cache). Bump the vN prefix whenever the
        # computed shape/semantics change so a deploy orphans stale entries immediately
        # instead of waiting for the TTL.
        # v2: tile sets derived from the TileSet.geo_zones association (was Detection.tile_set).
        # v3: key no longer folds in the count cache version.
        # v4: per-department payload gained sitadel_updated_detections_count.
        # v5: deleted=False filters removed from the computation (never set in the app).
        return "aigle:deployed_data:departments:v5"

    @staticmethod
    def _get_all_departments_cached() -> List[dict]:
        result = get_or_compute(
            DeployedDataService._cache_key(),
            DeployedDataService._compute_all_departments,
            DEPLOYED_DATA_CACHE_TTL,
        )
        return result or []

    @staticmethod
    def refresh_cache() -> List[dict]:
        """Recompute the dataset and (re)populate the cache, bypassing any cached value.

        Meant to be run out-of-band (see `warm_deployed_data_cache`) so HTTP requests
        always hit a warm cache instead of paying the cold computation cost.
        """
        departments = DeployedDataService._compute_all_departments()
        safe_cache_set(
            DeployedDataService._cache_key(), departments, DEPLOYED_DATA_CACHE_TTL
        )
        return departments

    @staticmethod
    def _compute_all_departments() -> List[dict]:
        # 1. Detection count per commune, in a single grouped scan. This both yields the
        #    per-commune "Détections" figure and tells us which communes (hence which
        #    departments) are deployed. No DISTINCT is needed: each Detection belongs to
        #    exactly one DetectionObject -> one commune.
        #    Count("detection_object") (== Count("id"), the FK is non-null) keeps both
        #    sides of the join answerable from indexes alone (index-only scans on the
        #    detection_object FK index and detobj_id_commune_idx).
        detections_by_commune = defaultdict(int)
        for row in (
            Detection.objects.filter(detection_object__commune_id__isnull=False)
            .values("detection_object__commune_id")
            .annotate(detections_count=Count("detection_object"))
        ):
            detections_by_commune[row["detection_object__commune_id"]] += row[
                "detections_count"
            ]

        if not detections_by_commune:
            return []

        # 1b. Detections whose validation status was last changed by the SITADEL import,
        #     per commune. Computed as its OWN query rather than a conditional Count in
        #     step 1: only ~2% of detection_data rows carry a change reason, so this is
        #     a small index-driven query (detectiondata_reason_idx), whereas folding it
        #     into step 1 LEFT JOINed the whole multi-GB detection_data table into the
        #     full-dataset aggregate (and its temp spill dominated the runtime).
        sitadel_updated_by_commune = defaultdict(int)
        for row in (
            Detection.objects.filter(
                detection_object__commune_id__isnull=False,
                detection_data__detection_validation_status_change_reason=DetectionValidationStatusChangeReason.SITADEL,
            )
            .values("detection_object__commune_id")
            .annotate(count=Count("detection_object"))
        ):
            sitadel_updated_by_commune[row["detection_object__commune_id"]] += row[
                "count"
            ]

        # 2. Metadata for those communes. This also tells us which departments are
        #    deployed.
        communes_by_department = defaultdict(list)
        for commune in (
            GeoCommune.objects.filter(id__in=list(detections_by_commune.keys()))
            .values("id", "uuid", "name", "department_id")
            .order_by("name")
        ):
            communes_by_department[commune["department_id"]].append(
                {
                    "uuid": commune["uuid"],
                    "name": commune["name"],
                    "detections_count": detections_by_commune[commune["id"]],
                }
            )

        department_ids = list(communes_by_department.keys())

        departments = list(
            GeoDepartment.objects.filter(id__in=department_ids)
            .values("id", "uuid", "name")
            .order_by("name")
        )

        if not departments:
            return []

        department_ids = [department["id"] for department in departments]

        # 3. All communes of the deployed departments, mapped to their department.
        #    Reused both for the parcel count and for resolving which department an
        #    association's geo_zone belongs to. We take ALL communes (not only those
        #    with detections) since associations may target any commune.
        commune_to_department = {
            row["id"]: row["department_id"]
            for row in GeoCommune.objects.filter(
                department_id__in=department_ids
            ).values("id", "department_id")
        }

        # Roll the per-commune SITADEL-updated counts (step 1) up to the department,
        # skipping communes that fell out with the commune->department map above.
        sitadel_updated_by_department = defaultdict(int)
        for commune_id, count in sitadel_updated_by_commune.items():
            department_id = commune_to_department.get(commune_id)
            if department_id is not None:
                sitadel_updated_by_department[department_id] += count

        # 4. Parcel count per department. The WHOLE parcel table is grouped by commune
        #    (a few thousand rows out) and mapped to departments in Python: no join to
        #    the commune table, and no `commune_id IN (...)` filter — shipping tens of
        #    thousands of ids bloats the statement for no gain since communes outside
        #    the deployed departments are simply skipped by the map lookup below.
        #    Count("commune_id") (== row count, the FK is non-null) makes this an
        #    index-only scan of the commune FK index instead of a ~7GB heap scan
        #    (measured 46s -> ~4s).
        parcel_count_by_department = defaultdict(int)
        for row in Parcel.objects.values("commune_id").annotate(
            count=Count("commune_id")
        ):
            department_id = commune_to_department.get(row["commune_id"])
            if department_id is not None:
                parcel_count_by_department[department_id] += row["count"]

        # 5. Map every geo_zone id (each department and ALL its communes) back to its
        #    department. A department's pk equals its GeoZone id (multi-table
        #    inheritance), which is what the `geo_zones` M2M stores.
        zone_to_department = {
            department_id: department_id for department_id in department_ids
        }
        zone_to_department.update(commune_to_department)
        all_zone_ids = list(department_ids) + list(commune_to_department.keys())

        user_groups_by_department = DeployedDataService._group_related_by_department(
            UserGroup.objects.filter(geo_zones__id__in=all_zone_ids)
            .values("uuid", "name", "geo_zones__id")
            .distinct(),
            zone_to_department,
            lambda row: {"uuid": row["uuid"], "name": row["name"]},
        )

        # Users (uuid + email) for every user group surfaced above, in one query.
        user_group_uuids = {
            user_group["uuid"]
            for groups in user_groups_by_department.values()
            for user_group in groups.values()
        }
        users_by_user_group = defaultdict(list)
        for row in (
            UserUserGroup.objects.filter(user_group__uuid__in=user_group_uuids)
            .values("user_group__uuid", "user__uuid", "user__email")
            .order_by("user__email")
        ):
            users_by_user_group[row["user_group__uuid"]].append(
                {"uuid": row["user__uuid"], "email": row["user__email"]}
            )

        custom_zones_by_department = DeployedDataService._group_related_by_department(
            GeoCustomZone.objects.filter(geo_zones__id__in=all_zone_ids)
            .values(
                "uuid",
                "name",
                "color",
                "geo_custom_zone_category__name",
                "geo_custom_zone_category__color",
                "geo_zones__id",
            )
            .distinct(),
            zone_to_department,
            lambda row: {
                "uuid": row["uuid"],
                "name": row["name"],
                "category_name": row["geo_custom_zone_category__name"],
                # mirror the frontend convention: category color wins when categorized
                "color": row["geo_custom_zone_category__color"] or row["color"],
            },
        )

        # Tile sets associated (through their geo_zones M2M) to the department or any of
        # its communes — the same geographic association used for user groups and custom
        # zones above. See the class docstring for why this is preferred over
        # Detection.tile_set.
        tile_sets_by_department = DeployedDataService._group_related_by_department(
            TileSet.objects.filter(geo_zones__id__in=all_zone_ids)
            .values("uuid", "name", "date", "geo_zones__id")
            .distinct(),
            zone_to_department,
            lambda row: {
                "uuid": row["uuid"],
                "name": row["name"],
                "date": row["date"],
            },
        )

        # 6. Assemble the per-department payload.
        result = []
        for department in departments:
            department_id = department["id"]
            communes = communes_by_department.get(department_id, [])

            user_groups = [
                {**user_group, "users": users_by_user_group.get(user_group["uuid"], [])}
                for user_group in user_groups_by_department.get(
                    department_id, {}
                ).values()
            ]
            user_groups.sort(key=lambda user_group: user_group["name"])

            custom_zones = sorted(
                custom_zones_by_department.get(department_id, {}).values(),
                key=lambda custom_zone: (
                    custom_zone["category_name"] or custom_zone["name"]
                ),
            )

            tile_sets = sorted(
                tile_sets_by_department.get(department_id, {}).values(),
                key=lambda tile_set: tile_set["date"],
                reverse=True,
            )

            result.append(
                {
                    "uuid": department["uuid"],
                    "name": department["name"],
                    "parcels_count": parcel_count_by_department.get(department_id, 0),
                    "sitadel_updated_detections_count": sitadel_updated_by_department.get(
                        department_id, 0
                    ),
                    "communes_with_detections_count": len(communes),
                    "communes": communes,
                    "user_groups": user_groups,
                    "custom_zones": custom_zones,
                    "tile_sets": tile_sets,
                }
            )

        return result

    @staticmethod
    def _group_related_by_department(rows, zone_to_department, build_item):
        """Group rows (each carrying a matched `geo_zones__id`) by department.

        Returns department_id -> {item_uuid: item}, deduplicating items that match the
        department through several of its geo zones.
        """
        grouped = defaultdict(dict)
        for row in rows:
            department_id = zone_to_department.get(row["geo_zones__id"])
            if department_id is None:
                continue
            grouped[department_id][row["uuid"]] = build_item(row)
        return grouped
