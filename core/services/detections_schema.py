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
