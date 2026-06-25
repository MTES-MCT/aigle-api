"""Tests for DetectionsSchemaService — the DB-free parts.

The queries need the external `detections` schema (absent from the test DB), so
these cover what can silently break without it: the column lists the SELECTs are
built from must stay in sync with their serializers.
"""

from core.services.detections_schema import (
    BATCH_COLUMNS,
    INFERENCE_COLUMNS,
    BatchRowSerializer,
    DetectionRowSerializer,
)


def test_inference_columns_track_the_serializer():
    # The SELECT column list is derived from the serializer — drift would break
    # the dict(zip(columns, row)) mapping silently.
    assert INFERENCE_COLUMNS == list(DetectionRowSerializer().get_fields()) + [
        "geometry"
    ]


def test_batch_columns_track_the_serializer():
    assert BATCH_COLUMNS == list(BatchRowSerializer().get_fields().keys())
