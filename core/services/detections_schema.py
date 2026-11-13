from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.db import connection
from rest_framework import serializers

from core.constants.geo import LAYER_TYPE_CATEGORY_NAME_MAP
from core.models.detection import DetectionSource
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.utils.string import normalize

# The whole external ML schema we read from. Fixed: only these tables are used.
SCHEMA = "detections"
INFERENCE_TABLE = "inference"


class DetectionRowSerializer(serializers.Serializer):
    """Shape of a row in detections.inference."""

    score = serializers.FloatField()
    id = serializers.IntegerField(required=True)
    address = serializers.CharField(allow_blank=True, allow_null=True)
    object_type = serializers.CharField()
    detection_control_status = serializers.ChoiceField(
        choices=DetectionControlStatus.choices,
        required=False,
        allow_null=True,
        default=DetectionControlStatus.NOT_CONTROLLED,
    )
    detection_validation_status = serializers.ChoiceField(
        choices=DetectionValidationStatus.choices,
        required=False,
        allow_null=True,
        default=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
    )
    detection_prescription_status = serializers.ChoiceField(
        choices=DetectionPrescriptionStatus.choices,
        required=False,
        allow_null=True,
        # without a default the key is absent from validated_data when the row omits it
        default=None,
    )
    detection_source = serializers.ChoiceField(
        choices=DetectionSource.choices,
        required=False,
        allow_null=True,
        default=DetectionSource.ANALYSIS,
    )
    user_reviewed = serializers.BooleanField(
        default=False,
        allow_null=True,
    )
    tile_x = serializers.IntegerField(required=False, allow_null=True)
    tile_y = serializers.IntegerField(required=False, allow_null=True)


# geometry is read from the table but popped before serializer validation.
INFERENCE_COLUMNS = list(DetectionRowSerializer().get_fields()) + ["geometry"]


class BatchRowSerializer(serializers.Serializer):
    """Shape of a row in detections.batch."""

    id = serializers.IntegerField()
    batch_name = serializers.CharField(allow_blank=True, allow_null=True)
    created_at = serializers.DateTimeField(required=False, allow_null=True)
    model_id = serializers.IntegerField(required=False, allow_null=True)
    batch_tiles_url = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    run_id = serializers.IntegerField(required=False, allow_null=True)


BATCH_COLUMNS = list(BatchRowSerializer().get_fields().keys())


@dataclass
class InferenceFilter:
    batch_id: str


# A batch as deployed: its run's geozone and source imagery year come with it.
DEPLOYMENT_BATCH_COLUMNS = [
    "id",
    "batch_name",
    "created_at",
    "batch_tiles_url",
    "geozone_id",
    "src_image_year",
    "run_id",
]

# Columns read for the data-deployment listing.
ZAE_LAYER_COLUMNS = [
    "id",
    "layer_name",
    "layer_type",
    "layer_year",
    "department_code",
    "created_at",
]


# A plan's runs, as shown in the plan listing.
PLAN_RUN_COLUMNS = [
    "id",
    "plan_id",
    "run_name",
    "run_type",
    "status",
    "src_image_year",
    "created_at",
    "geozone_id",
]

PLAN_COLUMNS = [
    "id",
    "geozone_insee_code",
    "created_at",
    "plan_status",
    "plan_mode",
    "plan_type",
    "run_ids",
]


@dataclass
class SearchTerm:
    """The `q` of the imports listings: matched against names (ILIKE on `text`, or on
    `normalized` for the app's accent-free geozone names), codes, and ids (`number`)."""

    text: str
    normalized: str
    number: Optional[int]

    @staticmethod
    def parse(q: Optional[str]) -> Optional["SearchTerm"]:
        text = (q or "").strip()
        if not text:
            return None
        # a postgres bigint: a longer digit string can't be an id
        number = int(text) if text.isdigit() and len(text) < 19 else None
        return SearchTerm(text=text, normalized=normalize(text), number=number)

    @property
    def contains(self) -> str:
        return f"%{self.text}%"


# A geozone of the app with its department (itself for a department), to match a
# search against its name, its own code (commune iso / epci siren / department insee)
# and its department's name and code. Commune and EPCI rows carry their parent
# department; a department row is its own.
_GEOZONE_SEARCH_FROM = (
    "FROM public.core_geozone gz "
    "LEFT JOIN public.core_geocommune gc ON gc.geozone_ptr_id = gz.id "
    "LEFT JOIN public.core_geoepci ge ON ge.geozone_ptr_id = gz.id "
    "LEFT JOIN public.core_geodepartment gd "
    "ON gd.geozone_ptr_id = COALESCE(gc.department_id, ge.department_id, gz.id) "
    "LEFT JOIN public.core_geozone gdz ON gdz.id = gd.geozone_ptr_id"
)
# the zone's own code, what detections.plan.geozone_insee_code holds
_GEOZONE_OWN_CODE = (
    "COALESCE(gc.iso_code, ge.siren_code, "
    "CASE WHEN gd.geozone_ptr_id = gz.id THEN gd.insee_code END)"
)


def _geozone_search_sql(geozone_predicate: str, term: SearchTerm) -> Tuple[str, list]:
    """EXISTS clause: the geozone picked by `geozone_predicate` (SQL over the gz/gc/ge/gd
    aliases) matches the search on its name, code, or department name / code."""
    conditions = [
        "gc.iso_code ILIKE %s",
        "ge.siren_code ILIKE %s",
        "UPPER(gd.insee_code) = UPPER(%s)",
    ]
    params: list = [f"{term.text}%", f"{term.text}%", term.text]
    # punctuation-only input normalizes to "": it would match every name
    if term.normalized:
        conditions += ["gz.name_normalized LIKE %s", "gdz.name_normalized LIKE %s"]
        params += [f"%{term.normalized}%"] * 2
    return (
        f"EXISTS (SELECT 1 {_GEOZONE_SEARCH_FROM} WHERE {geozone_predicate} "
        f"AND ({' OR '.join(conditions)}))",
        params,
    )


def _department_search_sql(code_column: str, term: SearchTerm) -> Tuple[str, list]:
    """A department code column matches the search on the code or the name of the
    department it designates."""
    conditions = [f"UPPER({code_column}) = UPPER(%s)"]
    params: list = [term.text]
    if term.normalized:
        conditions.append(
            f"{code_column} IN (SELECT gd.insee_code FROM public.core_geodepartment gd "
            "JOIN public.core_geozone gdz ON gdz.id = gd.geozone_ptr_id "
            "WHERE gdz.name_normalized LIKE %s)"
        )
        params.append(f"%{term.normalized}%")
    return f"({' OR '.join(conditions)})", params


def _or(parts: List[Tuple[str, list]]) -> Tuple[str, list]:
    return (
        "(" + " OR ".join(sql for sql, _ in parts) + ")",
        [param for _, params in parts for param in params],
    )


class DetectionsSchemaService:
    """Read-only access to the ML pipeline's external `detections` schema
    (tables: batch, inference, model, run) — distinct from the app's own
    Detection models. Only what import_detections needs for now."""

    @staticmethod
    def get_batch(batch_id: str) -> Optional[Dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(BATCH_COLUMNS)} FROM {SCHEMA}.batch WHERE id = %s",
                [batch_id],
            )
            row = cursor.fetchone()
        return dict(zip(BATCH_COLUMNS, row)) if row else None

    @staticmethod
    def get_distinct_object_types(filter: InferenceFilter) -> List[str]:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT DISTINCT object_type FROM {SCHEMA}.{INFERENCE_TABLE} "
                "WHERE batch_id = %s",
                [filter.batch_id],
            )
            return [row[0] for row in cursor.fetchall()]

    @staticmethod
    def count_inferences(filter: InferenceFilter) -> int:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM {SCHEMA}.{INFERENCE_TABLE} WHERE batch_id = %s",
                [filter.batch_id],
            )
            return cursor.fetchone()[0]

    @staticmethod
    def get_inference_rows(filter: InferenceFilter) -> Iterable[Dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(INFERENCE_COLUMNS)} FROM {SCHEMA}.{INFERENCE_TABLE} "
                "WHERE batch_id = %s ORDER BY score DESC",
                [filter.batch_id],
            )
            for row in cursor:
                yield dict(zip(INFERENCE_COLUMNS, row))

    @staticmethod
    def get_run_geozones(
        q: Optional[str] = None,
        batch_created_at_min: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[int, List[Dict[str, Any]]]:
        """Distinct geozones that have at least one run (one row per collectivity),
        with the most recent run date and the ids of their runs (newest first). Optionally restricted to geozones owning a
        batch matching the `q` (batch name) / `batch_created_at_min` filters."""
        where_sql, params = DetectionsSchemaService._run_geozones_where(
            q, batch_created_at_min
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(DISTINCT r.geozone_id) FROM {SCHEMA}.run r {where_sql}",
                params,
            )
            count = cursor.fetchone()[0]

            cursor.execute(
                f"SELECT r.geozone_id, MAX(r.created_at), "
                "ARRAY_AGG(r.id ORDER BY r.created_at DESC NULLS LAST, r.id DESC) "
                f"FROM {SCHEMA}.run r {where_sql} "
                "GROUP BY r.geozone_id "
                "ORDER BY MAX(r.created_at) DESC NULLS LAST, r.geozone_id DESC "
                "LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            cols = ["geozone_id", "created_at", "run_ids"]
            rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        return count, rows

    @staticmethod
    def _run_geozones_where(
        q: Optional[str], batch_created_at_min: Optional[str]
    ) -> tuple[str, List[Any]]:
        """Runs matching `q` on one of their batches (name, tiles url, id), their own id
        or plan id, or their geozone (name, code, department) — and owning a batch
        created since `batch_created_at_min`. A batch matched by `q` must also be the one
        satisfying the date."""
        conditions = ["r.geozone_id IS NOT NULL"]
        params: List[Any] = []
        date_sql, date_params = (
            (" AND b.created_at >= %s", [batch_created_at_min])
            if batch_created_at_min
            else ("", [])
        )
        batch_exists = f"EXISTS (SELECT 1 FROM {SCHEMA}.batch b WHERE b.run_id = r.id{{}}{date_sql})"

        term = SearchTerm.parse(q)
        if term:
            batch_match = ["b.batch_name ILIKE %s", "b.batch_tiles_url ILIKE %s"]
            batch_params: List[Any] = [term.contains, term.contains]
            own_match = [_geozone_search_sql("gz.id = r.geozone_id", term)]
            if term.number is not None:
                batch_match.append("b.id = %s")
                batch_params.append(term.number)
                own_match.append(("r.id = %s OR r.plan_id = %s", [term.number] * 2))
            own_sql, own_params = _or(own_match)
            if batch_created_at_min:
                own_sql = f"({own_sql} AND {batch_exists.format('')})"
                own_params = [*own_params, *date_params]
            q_sql, q_params = _or(
                [
                    (
                        batch_exists.format(f" AND ({' OR '.join(batch_match)})"),
                        [*batch_params, *date_params],
                    ),
                    (own_sql, own_params),
                ]
            )
            conditions.append(q_sql)
            params.extend(q_params)
        elif batch_created_at_min:
            conditions.append(batch_exists.format(""))
            params.extend(date_params)
        return "WHERE " + " AND ".join(conditions), params

    @staticmethod
    def get_batches_by_geozone(geozone_ids: List[int]) -> List[Dict[str, Any]]:
        """All batches belonging to the given geozones (joined through run).
        src_image_year (the run's source imagery year) is used to name the
        per-batch TileSet during deployment."""
        if not geozone_ids:
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT b.id, b.batch_name, b.created_at, b.batch_tiles_url, "
                f"r.geozone_id, r.src_image_year, b.run_id FROM {SCHEMA}.batch b "
                f"JOIN {SCHEMA}.run r ON r.id = b.run_id "
                "WHERE r.geozone_id = ANY(%s) ORDER BY b.created_at DESC NULLS LAST",
                [list(geozone_ids)],
            )
            return [
                dict(zip(DEPLOYMENT_BATCH_COLUMNS, row)) for row in cursor.fetchall()
            ]

    @staticmethod
    def get_deployment_batch(batch_id: int) -> Optional[Dict[str, Any]]:
        """One batch, shaped like get_batches_by_geozone, whatever the geozone of its run
        (LEFT JOIN: none, or no run at all — then it has no src_image_year either)."""
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT b.id, b.batch_name, b.created_at, b.batch_tiles_url, "
                f"r.geozone_id, r.src_image_year, b.run_id FROM {SCHEMA}.batch b "
                f"LEFT JOIN {SCHEMA}.run r ON r.id = b.run_id WHERE b.id = %s",
                [batch_id],
            )
            row = cursor.fetchone()
        return dict(zip(DEPLOYMENT_BATCH_COLUMNS, row)) if row else None

    @staticmethod
    def get_batches(
        q: Optional[str] = None, limit: int = 20, offset: int = 0
    ) -> tuple[int, List[Dict[str, Any]]]:
        """Flat, paginated list of every batch (newest first), optionally searched on
        batch_name, the batch / run / plan id, or the geozone of its run (name, code,
        department). LEFT JOIN on run: a batch whose run has no geozone is still listed,
        it just can't be deployed."""
        where_sql, params = "", []
        term = SearchTerm.parse(q)
        if term:
            parts = [
                ("b.batch_name ILIKE %s", [term.contains]),
                _geozone_search_sql("gz.id = r.geozone_id", term),
            ]
            if term.number is not None:
                parts.append(
                    ("b.id = %s OR b.run_id = %s OR r.plan_id = %s", [term.number] * 3)
                )
            where_sql, params = _or(parts)
            where_sql = f"WHERE {where_sql}"
        cols = [
            "id",
            "batch_name",
            "created_at",
            "batch_tiles_url",
            "geozone_id",
            "run_id",
        ]
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM {SCHEMA}.batch b "
                f"LEFT JOIN {SCHEMA}.run r ON r.id = b.run_id {where_sql}",
                params,
            )
            count = cursor.fetchone()[0]

            cursor.execute(
                f"SELECT b.id, b.batch_name, b.created_at, b.batch_tiles_url, "
                f"r.geozone_id, b.run_id FROM {SCHEMA}.batch b "
                f"LEFT JOIN {SCHEMA}.run r ON r.id = b.run_id {where_sql} "
                "ORDER BY b.created_at DESC NULLS LAST, b.id DESC LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        return count, rows

    @staticmethod
    def get_zae_department_codes(
        q: Optional[str] = None, limit: int = 20, offset: int = 0
    ) -> tuple[int, List[str]]:
        """Paginated distinct department codes owning at least one zae layer (matching
        `q` when given, see _zae_search_sql) — the grouping key of the zae listing."""
        conditions = ["department_code IS NOT NULL"]
        params: List[Any] = []
        term = SearchTerm.parse(q)
        if term:
            search_sql, search_params = DetectionsSchemaService._zae_search_sql(term)
            conditions.append(search_sql)
            params.extend(search_params)
        where_sql = "WHERE " + " AND ".join(conditions)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(DISTINCT department_code) FROM {SCHEMA}.zae_layer "
                f"{where_sql}",
                params,
            )
            count = cursor.fetchone()[0]

            cursor.execute(
                f"SELECT DISTINCT department_code FROM {SCHEMA}.zae_layer {where_sql} "
                "ORDER BY department_code LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            return count, [row[0] for row in cursor.fetchall()]

    @staticmethod
    def get_zae_layers(
        department_codes: List[str], q: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if not department_codes:
            return []
        conditions = ["department_code = ANY(%s)"]
        params: List[Any] = [list(department_codes)]
        term = SearchTerm.parse(q)
        if term:
            search_sql, search_params = DetectionsSchemaService._zae_search_sql(term)
            conditions.append(search_sql)
            params.extend(search_params)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(ZAE_LAYER_COLUMNS)} FROM {SCHEMA}.zae_layer "
                f"WHERE {' AND '.join(conditions)} ORDER BY layer_name",
                params,
            )
            return [dict(zip(ZAE_LAYER_COLUMNS, row)) for row in cursor.fetchall()]

    @staticmethod
    def _zae_search_sql(term: SearchTerm) -> Tuple[str, List[Any]]:
        """A zae layer matches on its name, id, type (code or label), or its department
        (code or name) — a matching department keeps all of its layers."""
        parts = [
            ("layer_name ILIKE %s OR layer_type ILIKE %s", [term.contains] * 2),
            _department_search_sql("department_code", term),
        ]
        type_codes = [
            code
            for code, name in LAYER_TYPE_CATEGORY_NAME_MAP.items()
            if term.normalized and term.normalized in normalize(name)
        ]
        if type_codes:
            parts.append(("layer_type = ANY(%s)", [type_codes]))
        if term.number is not None:
            parts.append(("id = %s", [term.number]))
        return _or(parts)

    @staticmethod
    def get_plans(
        q: Optional[str] = None, limit: int = 20, offset: int = 0
    ) -> tuple[int, List[Dict[str, Any]]]:
        """Paginated plans (newest first) with the ids of their runs (newest first).
        `q` matches the plan id, its geozone code, type and status, its geozone (name,
        code, department: through the code, or the geozone of its runs), and its runs
        (id, name) and their batches (id, name)."""
        where_sql, params = "", []
        term = SearchTerm.parse(q)
        if term:
            run_parts = [
                ("r.run_name ILIKE %s", [term.contains]),
                _geozone_search_sql("gz.id = r.geozone_id", term),
                (
                    f"EXISTS (SELECT 1 FROM {SCHEMA}.batch b WHERE b.run_id = r.id "
                    "AND (b.batch_name ILIKE %s"
                    + (" OR b.id = %s))" if term.number is not None else "))"),
                    [term.contains]
                    + ([term.number] if term.number is not None else []),
                ),
            ]
            if term.number is not None:
                run_parts.append(("r.id = %s", [term.number]))
            run_sql, run_params = _or(run_parts)
            parts = [
                (
                    "p.geozone_insee_code ILIKE %s OR p.plan_type ILIKE %s "
                    "OR p.plan_status ILIKE %s",
                    [f"{term.text}%", term.contains, term.contains],
                ),
                _geozone_search_sql(
                    f"{_GEOZONE_OWN_CODE} = p.geozone_insee_code", term
                ),
                (
                    f"EXISTS (SELECT 1 FROM {SCHEMA}.run r "
                    f"WHERE r.plan_id = p.id AND {run_sql})",
                    run_params,
                ),
            ]
            if term.number is not None:
                parts.append(("p.id = %s", [term.number]))
            where_sql, params = _or(parts)
            where_sql = f"WHERE {where_sql}"

        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {SCHEMA}.plan p {where_sql}", params)
            count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT p.id, p.geozone_insee_code, p.created_at, p.plan_status, "
                "p.plan_mode, p.plan_type, "
                f"ARRAY(SELECT r.id FROM {SCHEMA}.run r WHERE r.plan_id = p.id "
                "ORDER BY r.created_at DESC NULLS LAST, r.id DESC) "
                f"FROM {SCHEMA}.plan p {where_sql} "
                "ORDER BY p.created_at DESC NULLS LAST, p.id DESC LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            rows = [dict(zip(PLAN_COLUMNS, row)) for row in cursor.fetchall()]
        return count, rows

    @staticmethod
    def get_plan(plan_id: int) -> Optional[Dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT p.id, p.geozone_insee_code, p.created_at, p.plan_status, "
                "p.plan_mode, p.plan_type, "
                f"ARRAY(SELECT r.id FROM {SCHEMA}.run r WHERE r.plan_id = p.id "
                "ORDER BY r.created_at DESC NULLS LAST, r.id DESC) "
                f"FROM {SCHEMA}.plan p WHERE p.id = %s",
                [plan_id],
            )
            row = cursor.fetchone()
        return dict(zip(PLAN_COLUMNS, row)) if row else None

    @staticmethod
    def get_runs_by_plan(plan_ids: List[int]) -> List[Dict[str, Any]]:
        if not plan_ids:
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(PLAN_RUN_COLUMNS)} FROM {SCHEMA}.run "
                "WHERE plan_id = ANY(%s) ORDER BY created_at DESC NULLS LAST, id DESC",
                [list(plan_ids)],
            )
            return [dict(zip(PLAN_RUN_COLUMNS, row)) for row in cursor.fetchall()]

    @staticmethod
    def get_batches_by_plan(plan_ids: List[int]) -> List[Dict[str, Any]]:
        """The batches of the plans' runs, shaped like get_batches_by_geozone plus the
        plan_id."""
        if not plan_ids:
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT b.id, b.batch_name, b.created_at, b.batch_tiles_url, "
                f"r.geozone_id, r.src_image_year, b.run_id, r.plan_id "
                f"FROM {SCHEMA}.batch b JOIN {SCHEMA}.run r ON r.id = b.run_id "
                "WHERE r.plan_id = ANY(%s) ORDER BY b.created_at DESC NULLS LAST, b.id DESC",
                [list(plan_ids)],
            )
            return [
                dict(zip([*DEPLOYMENT_BATCH_COLUMNS, "plan_id"], row))
                for row in cursor.fetchall()
            ]
