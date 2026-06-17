import os
from collections import defaultdict
from typing import List, Optional

from django.db import connection
from django.db.models import Count

from core.models.detection_data import DetectionValidationStatusChangeReason
from core.models.detection_object import DetectionObject
from core.models.geo_commune import GeoCommune
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_department import GeoDepartment
from core.models.parcel import Parcel
from core.models.tile_set import TileSet
from core.models.user_group import UserGroup, UserUserGroup
from core.utils.cache import (
    get_deployed_data_cache_version,
    get_or_compute,
    invalidate_deployed_data_cache,
    safe_cache_set,
)
from core.utils.string import normalize

# The SUPER_ADMIN "deployed data" overview is served by two cached tiers so the common
# case (loading the department list) never pays for the full per-department breakdown:
#
# - SUMMARY (list view): one lean, all-departments aggregate — per-commune detection
#   counts (which tell us which departments are deployed and feed the per-commune
#   threshold), plus distinct user counts and tile-set years. Cached under the summary
#   key, refreshed out-of-band by `manage.py warm_deployed_data_cache`.
# - DETAIL (one department): the full breakdown — per-commune and per-tile-set detection
#   counts (total + in-custom-zone), parcels, SITADEL parcels, user groups, custom zones,
#   tile sets — computed lazily the first time a department's detail page is opened and
#   cached under a per-department key. Every query is scoped to that one department's
#   communes (a small `commune_id IN (...)`) so it stays index-driven and cheap; the
#   list view never triggers it.
#
# Both tiers fold in get_deployed_data_cache_version(): warm_deployed_data_cache bumps it
# (O(1) invalidation of the summary AND every per-department detail) then recomputes the
# summary, so details refresh lazily on next access. The version is bumped ONLY by that
# command (run after a detection/parcel import), never on individual writes — this is a
# slow-moving deployment-status figure that tolerates bounded staleness (the TTL is the
# upper bound). Folding in the per-write count-cache version instead would invalidate the
# heavy aggregate on essentially every edit in the country.
#
# Performance: the only full-dataset scan is the summary's DetectionObject-by-commune
# count. Count("commune_id") (non-null under the filter, in the partial
# detobj_id_commune_idx) keeps it on an index-only scan instead of a multi-GB heap scan.
# None of the queries filter deleted=False: nothing in the app soft-deletes these rows
# and `deleted` is in no index, so the filter would only force heap access.
#
# DETAIL performance: a department's detail used to scan whole tables for EVERY query
# because it filtered on `commune_id IN (<all the department's communes>)`. A department
# has hundreds of (mostly empty) communes, so that IN-list both (a) ballooned the query
# and (b) wrecked the planner's cardinality estimate, which then chose hash joins that
# full-scanned the multi-GB detection tables even for departments with a handful of
# detections (a 15-object department took ~8s). The detail now first finds the POPULATED
# communes (those that actually hold a detection object — one cheap index-only GROUP BY)
# and scopes the detection/parcel queries to just those, so a sparse department seeks a
# few rows instead of scanning everything. The per-tile-set total and in-custom-zone
# counts are gathered in a single detection scan (conditional aggregation) instead of two.
DEPLOYED_DATA_CACHE_TTL = int(os.environ.get("DEPLOYED_DATA_CACHE_TTL", 24 * 60 * 60))

# Bump when the cached SHAPE/semantics change so a deploy orphans stale entries
# immediately (alongside the runtime version counter, which only handles data freshness).
# v9: per-commune figures count detection OBJECTS again (per-tile-set stays detections).
# v10: detail scoped to populated communes; sitadel count is now detection-object driven.
_CACHE_SCHEMA = "v10"


class DeployedDataService:
    """Aggregates "deployed data" statistics per department for the SUPER_ADMIN dashboard.

    A department is considered "deployed" as soon as at least one of its communes holds
    a detection (Detection -> DetectionObject.commune). Departments without any detection
    are excluded.

    Counts are reported as a total plus the subset that falls inside at least one custom
    zone ("zone à enjeux" / ZAE). The entity differs by grouping: per COMMUNE the figure
    counts detection OBJECTS (a real-world object detected across several tile sets/years
    is one object); per TILE SET it counts DETECTIONS (Detection rows — the per-tile-set
    artifact, the only level at which a tile-set link exists).

    User groups, custom zones and tile sets are reported when they are associated (through
    their `geo_zones` M2M) either to the department itself or to any of its communes.

    Tile sets in the "fonds de carte" list are intentionally taken from that geographic
    association and NOT from `Detection.tile_set`: a detection's tile set is merely the
    imagery layer it was drawn/analysed on, which is not geographically scoped — the very
    same tile set appears on detections all over the country. The per-tile-set DETECTION
    breakdown (`detections_by_tile_set`) does use Detection.tile_set, but scoped to the
    department's own detections, which is meaningful.
    """

    # --- Public API -------------------------------------------------------------

    @staticmethod
    def get_departments_summary(
        q: Optional[str] = None, min_commune_detections: int = 0
    ) -> List[dict]:
        """Lightweight per-department rows for the list view (no nested detail).

        Carries only what the list table needs (commune count, distinct user count and
        the tile-set years). The `q` search and the per-commune detection threshold are
        applied in Python over the cached summary so every request hits the cache.
        """
        summary = DeployedDataService._get_summary_cached()
        needle = normalize(q) if q else None

        result = []
        for department in summary:
            if needle and needle not in normalize(department["name"]):
                continue

            counts = department["commune_detection_counts"]
            if min_commune_detections > 0:
                communes_count = sum(
                    1 for count in counts if count >= min_commune_detections
                )
            else:
                communes_count = len(counts)
            if communes_count == 0:
                continue

            result.append(
                {
                    "uuid": department["uuid"],
                    "name": department["name"],
                    "communes_with_detections_count": communes_count,
                    "users_count": department["users_count"],
                    "tile_set_years": department["tile_set_years"],
                }
            )

        return result

    @staticmethod
    def get_department_deployed_data(
        uuid, min_commune_detections: int = 0
    ) -> Optional[dict]:
        """Full deployed-data detail for a single department, computed and cached lazily.

        Returns None when the department is unknown or not deployed (so the view answers
        404), or when the per-commune threshold leaves it with no qualifying commune (so
        the detail stays consistent with the list row that was clicked).
        """
        department = get_or_compute(
            DeployedDataService._detail_cache_key(uuid),
            lambda: DeployedDataService._compute_department_detail(uuid),
            DEPLOYED_DATA_CACHE_TTL,
        )
        if department is None:
            return None

        return DeployedDataService._apply_min_commune_detections(
            department, min_commune_detections
        )

    @staticmethod
    def refresh_cache() -> List[dict]:
        """Recompute and (re)populate the SUMMARY cache AND every per-department detail.

        Meant to be run out-of-band (see `warm_deployed_data_cache`) after an import so
        both the list view and every department detail page hit a warm cache. Bumping the
        version first orphans the old entries; we then recompute the summary and, because
        the version bump would otherwise leave every detail cold (the original footgun
        behind "the dashboard is slow when the cache isn't stored yet"), eagerly warm each
        department's detail under the new version too.
        """
        # Bump the version first: orphans the old summary AND all per-department details.
        invalidate_deployed_data_cache()
        summary = DeployedDataService._compute_summary()
        # _summary_cache_key() now reads the bumped version, so this writes under the new
        # version.
        safe_cache_set(
            DeployedDataService._summary_cache_key(), summary, DEPLOYED_DATA_CACHE_TTL
        )

        # Warm every department detail under the (now bumped) version so no one pays the
        # cold computation on the next page load. Each detail is keyed and cached by
        # get_or_compute, exactly as a lazy first access would do.
        for department in summary:
            DeployedDataService.get_department_deployed_data(department["uuid"])

        return summary

    # --- Threshold ---------------------------------------------------------------

    @staticmethod
    def _apply_min_commune_detections(
        department: dict, min_commune_detections: int
    ) -> Optional[dict]:
        """Apply the per-commune detection threshold to one cached department detail.

        Returns the department untouched when no threshold is set, a filtered copy when
        some communes qualify (the cached structure is shared and must never be mutated),
        or None when no commune qualifies — the department is no longer "deployed" at
        that threshold. Department-wide aggregates (parcels, SITADEL, detections by tile
        set) are left as-is; the threshold only scopes the commune list.
        """
        if min_commune_detections <= 0:
            return department

        communes = [
            commune
            for commune in department["communes"]
            if commune["detection_objects_count"] >= min_commune_detections
        ]
        if not communes:
            return None

        return {
            **department,
            "communes": communes,
            "communes_with_detections_count": len(communes),
        }

    # --- Cache keys --------------------------------------------------------------

    @staticmethod
    def _summary_cache_key() -> str:
        return (
            f"aigle:deployed_data:summary:{_CACHE_SCHEMA}:"
            f"{get_deployed_data_cache_version()}"
        )

    @staticmethod
    def _detail_cache_key(uuid) -> str:
        return (
            f"aigle:deployed_data:department:{uuid}:{_CACHE_SCHEMA}:"
            f"{get_deployed_data_cache_version()}"
        )

    @staticmethod
    def _get_summary_cached() -> List[dict]:
        result = get_or_compute(
            DeployedDataService._summary_cache_key(),
            DeployedDataService._compute_summary,
            DEPLOYED_DATA_CACHE_TTL,
        )
        return result or []

    # --- Summary computation (all departments, lean) -----------------------------

    @staticmethod
    def _compute_summary() -> List[dict]:
        # 1. Detection-OBJECT count per commune, in a single grouped scan. This tells us
        #    which communes (hence departments) are deployed and feeds the per-commune
        #    threshold applied at request time. Counts objects (not Detection rows) to
        #    match the commune table in the detail. Count("commune_id") (non-null under
        #    the filter, in the partial detobj_id_commune_idx) keeps it on index-only
        #    scans (see the module docstring).
        objects_by_commune = defaultdict(int)
        for row in (
            DetectionObject.objects.filter(commune_id__isnull=False)
            .values("commune_id")
            .annotate(count=Count("commune_id"))
        ):
            objects_by_commune[row["commune_id"]] += row["count"]

        if not objects_by_commune:
            return []

        # 2. Per-department list of its communes' object counts (the threshold input).
        commune_counts_by_department = defaultdict(list)
        for commune in GeoCommune.objects.filter(
            id__in=list(objects_by_commune.keys())
        ).values("id", "department_id"):
            commune_counts_by_department[commune["department_id"]].append(
                objects_by_commune[commune["id"]]
            )

        department_ids = list(commune_counts_by_department.keys())
        departments = list(
            GeoDepartment.objects.filter(id__in=department_ids)
            .values("id", "uuid", "name")
            .order_by("name")
        )
        if not departments:
            return []
        department_ids = [department["id"] for department in departments]

        # 3. Map every geo_zone id (each department and ALL its communes) to its
        #    department, so associations targeting any commune resolve to the department.
        commune_to_department = {
            row["id"]: row["department_id"]
            for row in GeoCommune.objects.filter(
                department_id__in=department_ids
            ).values("id", "department_id")
        }
        zone_to_department = {
            department_id: department_id for department_id in department_ids
        }
        zone_to_department.update(commune_to_department)
        all_zone_ids = list(department_ids) + list(commune_to_department.keys())

        # 4. Distinct users per department, across every group linked to the department
        #    or one of its communes (a group's geo_zones may span several departments).
        group_departments = defaultdict(set)
        for row in (
            UserGroup.objects.filter(geo_zones__id__in=all_zone_ids)
            .values("uuid", "geo_zones__id")
            .distinct()
        ):
            department_id = zone_to_department.get(row["geo_zones__id"])
            if department_id is not None:
                group_departments[row["uuid"]].add(department_id)

        users_by_group = defaultdict(set)
        if group_departments:
            for row in UserUserGroup.objects.filter(
                user_group__uuid__in=list(group_departments.keys())
            ).values("user_group__uuid", "user__uuid"):
                users_by_group[row["user_group__uuid"]].add(row["user__uuid"])

        users_by_department = defaultdict(set)
        for group_uuid, dept_ids in group_departments.items():
            members = users_by_group.get(group_uuid, set())
            for department_id in dept_ids:
                users_by_department[department_id].update(members)

        # 5. Tile-set years per department (from the geo_zones association).
        years_by_department = defaultdict(set)
        for row in (
            TileSet.objects.filter(geo_zones__id__in=all_zone_ids)
            .values("date", "geo_zones__id")
            .distinct()
        ):
            department_id = zone_to_department.get(row["geo_zones__id"])
            if department_id is not None:
                years_by_department[department_id].add(row["date"].year)

        # 6. Assemble the lean per-department summary.
        result = []
        for department in departments:
            department_id = department["id"]
            years = sorted(years_by_department.get(department_id, set()), reverse=True)
            result.append(
                {
                    "uuid": department["uuid"],
                    "name": department["name"],
                    # Kept internal (not serialized): the per-commune counts the threshold
                    # is applied to at request time.
                    "commune_detection_counts": commune_counts_by_department[
                        department_id
                    ],
                    "users_count": len(users_by_department.get(department_id, set())),
                    "tile_set_years": [str(year) for year in years],
                }
            )

        return result

    # --- Detail computation (one department, full) -------------------------------

    @staticmethod
    def _compute_department_detail(uuid) -> Optional[dict]:
        department = (
            GeoDepartment.objects.filter(uuid=uuid).values("id", "uuid", "name").first()
        )
        if department is None:
            return None
        department_id = department["id"]

        commune_rows = list(
            GeoCommune.objects.filter(department_id=department_id).values(
                "id", "uuid", "name"
            )
        )
        commune_ids = [commune["id"] for commune in commune_rows]
        if not commune_ids:
            return None

        # Per-commune DETECTION OBJECT counts, scoped to this department. The commune
        # table counts objects (a real-world object detected on several tile sets/years is
        # one object), NOT Detection rows — unlike the per-tile-set breakdown below.
        # Count("commune_id") keeps this on the partial commune index. This first pass
        # also tells us which communes are POPULATED (hold ≥1 object); the detection and
        # parcel queries below are scoped to just those so they seek instead of scanning
        # the whole multi-GB tables for the department's many empty communes.
        objects_by_commune = defaultdict(int)
        for row in (
            DetectionObject.objects.filter(commune_id__in=commune_ids)
            .values("commune_id")
            .annotate(count=Count("commune_id"))
        ):
            objects_by_commune[row["commune_id"]] += row["count"]

        if not objects_by_commune:
            return None  # department not deployed -> 404

        populated_commune_ids = list(objects_by_commune.keys())

        # Per-commune in-custom-zone OBJECT counts. The geo_custom_zones M2M join
        # multiplies an object sitting in several zones, so Count(distinct) the object id.
        objects_in_zone_by_commune = defaultdict(int)
        for row in (
            DetectionObject.objects.filter(
                commune_id__in=populated_commune_ids,
                geo_custom_zones__isnull=False,
            )
            .values("commune_id")
            .annotate(count=Count("id", distinct=True))
        ):
            objects_in_zone_by_commune[row["commune_id"]] += row["count"]

        communes = sorted(
            (
                {
                    "uuid": commune["uuid"],
                    "name": commune["name"],
                    "detection_objects_count": objects_by_commune[commune["id"]],
                    "detection_objects_in_custom_zone_count": (
                        objects_in_zone_by_commune.get(commune["id"], 0)
                    ),
                }
                for commune in commune_rows
                if commune["id"] in objects_by_commune
            ),
            key=lambda commune: commune["name"],
        )

        # Per-tile-set detection counts (total + in-custom-zone) for this department's
        # detections, gathered in a SINGLE detection scan via conditional aggregation
        # (instead of one query for the total and another for the in-zone subset). The
        # deduped LEFT JOIN to the custom-zone M2M means a detection whose object sits in
        # several zones is still counted once (matching the per-commune in-zone criteria),
        # while the planner stays on a stable hash-join plan (a per-row EXISTS filter
        # produced wildly unstable plans). Raw SQL because this conditional aggregation
        # over a deduped join has no clean ORM form; the commune ids are bound, not
        # interpolated.
        detections_by_tile_set = {}
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.tile_set_id,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE z.detectionobject_id IS NOT NULL) AS in_zone
                FROM core_detection d
                JOIN core_detectionobject o ON o.id = d.detection_object_id
                LEFT JOIN (
                    SELECT detectionobject_id
                    FROM core_detectionobject_geo_custom_zones
                    GROUP BY detectionobject_id
                ) z ON z.detectionobject_id = d.detection_object_id
                WHERE o.commune_id = ANY(%s)
                GROUP BY d.tile_set_id
                """,
                [populated_commune_ids],
            )
            for tile_set_id, total, in_zone in cursor.fetchall():
                detections_by_tile_set[tile_set_id] = (total, in_zone)

        tile_set_meta = {
            row["id"]: row
            for row in TileSet.objects.filter(
                id__in=list(detections_by_tile_set.keys())
            ).values("id", "uuid", "name", "date")
        }
        detections_by_tile_set_list = sorted(
            (
                {
                    "uuid": tile_set_meta[tile_set_id]["uuid"],
                    "name": tile_set_meta[tile_set_id]["name"],
                    "date": tile_set_meta[tile_set_id]["date"],
                    "detections_count": total,
                    "detections_in_custom_zone_count": in_zone,
                }
                for tile_set_id, (total, in_zone) in detections_by_tile_set.items()
                if tile_set_id in tile_set_meta
            ),
            key=lambda tile_set: tile_set["date"],
            reverse=True,
        )

        # Parcels in the department (all communes — a parcel exists independently of any
        # detection), and the subset "updated by SITADEL": a parcel carrying a detection
        # object whose detection has a SITADEL change reason. Driving this from the
        # department's detection objects (scoped to populated communes) — rather than from
        # all of the department's parcels — keeps the planner from scanning every SITADEL
        # detection in the country; Count(distinct parcel_id) collapses the join fan-out.
        parcels_count = Parcel.objects.filter(commune_id__in=commune_ids).count()
        sitadel_updated_parcels_count = DetectionObject.objects.filter(
            commune_id__in=populated_commune_ids,
            parcel_id__isnull=False,
            detections__detection_data__detection_validation_status_change_reason=DetectionValidationStatusChangeReason.SITADEL,
        ).aggregate(count=Count("parcel_id", distinct=True))["count"]

        # Associations (user groups + members, custom zones, tile sets) linked via the
        # geo_zones M2M to the department or any of its communes. Single department, so
        # everything collected here belongs to it — no department mapping needed.
        all_zone_ids = [department_id] + commune_ids

        user_groups = {
            row["uuid"]: {"uuid": row["uuid"], "name": row["name"], "users": []}
            for row in UserGroup.objects.filter(geo_zones__id__in=all_zone_ids)
            .values("uuid", "name")
            .distinct()
        }
        if user_groups:
            for row in (
                UserUserGroup.objects.filter(user_group__uuid__in=list(user_groups))
                .values("user_group__uuid", "user__uuid", "user__email")
                .order_by("user__email")
            ):
                user_groups[row["user_group__uuid"]]["users"].append(
                    {"uuid": row["user__uuid"], "email": row["user__email"]}
                )
        user_groups_list = sorted(user_groups.values(), key=lambda group: group["name"])

        custom_zones = {
            row["uuid"]: {
                "uuid": row["uuid"],
                "name": row["name"],
                "category_name": row["geo_custom_zone_category__name"],
                # mirror the frontend convention: category color wins when categorized
                "color": row["geo_custom_zone_category__color"] or row["color"],
            }
            for row in GeoCustomZone.objects.filter(geo_zones__id__in=all_zone_ids)
            .values(
                "uuid",
                "name",
                "color",
                "geo_custom_zone_category__name",
                "geo_custom_zone_category__color",
            )
            .distinct()
        }
        custom_zones_list = sorted(
            custom_zones.values(),
            key=lambda zone: zone["category_name"] or zone["name"],
        )

        tile_sets = {
            row["uuid"]: {
                "uuid": row["uuid"],
                "name": row["name"],
                "date": row["date"],
            }
            for row in TileSet.objects.filter(geo_zones__id__in=all_zone_ids)
            .values("uuid", "name", "date")
            .distinct()
        }
        tile_sets_list = sorted(
            tile_sets.values(), key=lambda tile_set: tile_set["date"], reverse=True
        )

        return {
            "uuid": department["uuid"],
            "name": department["name"],
            "parcels_count": parcels_count,
            "sitadel_updated_parcels_count": sitadel_updated_parcels_count,
            "communes_with_detections_count": len(communes),
            "communes": communes,
            "user_groups": user_groups_list,
            "custom_zones": custom_zones_list,
            "tile_sets": tile_sets_list,
            "detections_by_tile_set": detections_by_tile_set_list,
        }
