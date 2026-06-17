# Adds the only missing index: core_detection(batch_id, tile_set_id) is unindexed yet the
# per-import custom-zone association filters on it. Partial (batch_id NOT NULL) excludes
# interface-drawn rows. CONCURRENTLY (atomic=False) — a plain build would lock writes.
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0123_remove_duplicate_indexes"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="detection",
            index=models.Index(
                fields=["batch_id", "tile_set"],
                name="core_detec_batch_tileset_idx",
                condition=models.Q(batch_id__isnull=False),
            ),
        ),
    ]
