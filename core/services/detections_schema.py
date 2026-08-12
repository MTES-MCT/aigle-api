from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from django.db import connection
from rest_framework import serializers

from core.models.detection import DetectionSource
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)

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


# Columns read for the data-deployment listing.
ZAE_LAYER_COLUMNS = [
    "id",
    "layer_name",
    "layer_type",
    "layer_year",
    "department_code",
    "created_at",
]


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
        with the most recent run date. Optionally restricted to geozones owning a
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
                f"SELECT r.geozone_id, MAX(r.created_at) FROM {SCHEMA}.run r {where_sql} "
                "GROUP BY r.geozone_id "
                "ORDER BY MAX(r.created_at) DESC NULLS LAST, r.geozone_id DESC "
                "LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            cols = ["geozone_id", "created_at"]
            rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        return count, rows

    @staticmethod
    def _run_geozones_where(
        q: Optional[str], batch_created_at_min: Optional[str]
    ) -> tuple[str, List[Any]]:
        conditions = ["r.geozone_id IS NOT NULL"]
        params: List[Any] = []
        batch_conditions = []
        if q:
            batch_conditions.append(
                "(b.batch_name ILIKE %s OR b.batch_tiles_url ILIKE %s)"
            )
            params.extend([f"%{q}%", f"%{q}%"])
        if batch_created_at_min:
            batch_conditions.append("b.created_at >= %s")
            params.append(batch_created_at_min)
        if batch_conditions:
            conditions.append(
                f"EXISTS (SELECT 1 FROM {SCHEMA}.batch b "
                f"WHERE b.run_id = r.id AND {' AND '.join(batch_conditions)})"
            )
        return "WHERE " + " AND ".join(conditions), params

    @staticmethod
    def get_batches_by_geozone(geozone_ids: List[int]) -> List[Dict[str, Any]]:
        """All batches belonging to the given geozones (joined through run).
        src_image_year (the run's source imagery year) is used to name the
        per-batch TileSet during deployment."""
        if not geozone_ids:
            return []
        cols = [
            "id",
            "batch_name",
            "created_at",
            "batch_tiles_url",
            "geozone_id",
            "src_image_year",
        ]
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT b.id, b.batch_name, b.created_at, b.batch_tiles_url, "
                f"r.geozone_id, r.src_image_year FROM {SCHEMA}.batch b "
                f"JOIN {SCHEMA}.run r ON r.id = b.run_id "
                "WHERE r.geozone_id = ANY(%s) ORDER BY b.created_at DESC NULLS LAST",
                [list(geozone_ids)],
            )
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    @staticmethod
    def get_batches(
        q: Optional[str] = None, limit: int = 20, offset: int = 0
    ) -> tuple[int, List[Dict[str, Any]]]:
        """Flat, paginated list of every batch (newest first), optionally filtered on
        batch_name. LEFT JOIN on run: a batch whose run has no geozone is still listed,
        it just can't be deployed."""
        where_sql, params = (
            ("WHERE b.batch_name ILIKE %s", [f"%{q}%"]) if q else ("", [])
        )
        cols = ["id", "batch_name", "created_at", "batch_tiles_url", "geozone_id"]
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {SCHEMA}.batch b {where_sql}", params)
            count = cursor.fetchone()[0]

            cursor.execute(
                f"SELECT b.id, b.batch_name, b.created_at, b.batch_tiles_url, "
                f"r.geozone_id FROM {SCHEMA}.batch b "
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
        `q` on layer_name when given) — the grouping key of the zae listing."""
        conditions = ["department_code IS NOT NULL"]
        params: List[Any] = []
        if q:
            conditions.append("layer_name ILIKE %s")
            params.append(f"%{q}%")
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
        if q:
            conditions.append("layer_name ILIKE %s")
            params.append(f"%{q}%")
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(ZAE_LAYER_COLUMNS)} FROM {SCHEMA}.zae_layer "
                f"WHERE {' AND '.join(conditions)} ORDER BY layer_name",
                params,
            )
            return [dict(zip(ZAE_LAYER_COLUMNS, row)) for row in cursor.fetchall()]
