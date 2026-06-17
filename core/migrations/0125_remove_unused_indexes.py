# GATED — review before applying. Drops indexes prod pg_stat reports as 0-scan or shadowed.
# Re-confirm idx_scan ~0 (and that no batch job regresses) before merging. CONCURRENTLY (atomic=False).
from django.contrib.postgres.operations import RemoveIndexConcurrently
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0124_add_detection_batch_id_index"),
    ]

    operations = [
        RemoveIndexConcurrently(
            model_name="detection", name="core_detect_created_2495bb_idx"
        ),  # created_at
        RemoveIndexConcurrently(
            model_name="detection", name="core_detect_detecti_88fc62_idx"
        ),  # detection_source
        RemoveIndexConcurrently(
            model_name="detectiondata", name="core_detect_detecti_d931b4_idx"
        ),  # detection_validation_status
        RemoveIndexConcurrently(
            model_name="detectiondata", name="core_detect_detecti_df0c9b_idx"
        ),  # detection_prescription_status
        RemoveIndexConcurrently(
            model_name="analyticlog", name="core_analyt_created_6b9809_idx"
        ),  # (created_at, analytic_log_type)
        RemoveIndexConcurrently(
            model_name="tileset", name="core_tilese_tile_se_0de645_idx"
        ),  # tile_set_status
        RemoveIndexConcurrently(
            model_name="tileset", name="core_tilese_tile_se_efc33c_idx"
        ),  # tile_set_type
        RemoveIndexConcurrently(
            model_name="tileset", name="core_tilese_tile_se_59c3e2_idx"
        ),  # (tile_set_status, date)
    ]
