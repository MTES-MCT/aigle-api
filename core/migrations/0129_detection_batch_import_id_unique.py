# Makes re-deploying a batch a no-op at the DB level: one detection per (batch, source
# row). Built as a partial unique INDEX CONCURRENTLY rather than AddConstraint — the
# plain build takes ACCESS EXCLUSIVE on core_detection, which the 10s lock_timeout in
# settings would abort. A conditional UniqueConstraint compiles to exactly this index,
# so SeparateDatabaseAndState lets Django's state track it as the constraint.
#
# Fails if duplicates already exist. Check first:
#   SELECT batch_id, import_id, count(*), array_agg(id)
#   FROM core_detection WHERE import_id IS NOT NULL
#   GROUP BY batch_id, import_id HAVING count(*) > 1;
# A failed CONCURRENTLY build leaves an INVALID index behind — drop it before retrying:
#   DROP INDEX CONCURRENTLY IF EXISTS detection_batch_import_id_unique;
from django.db import migrations, models

INDEX_NAME = "detection_batch_import_id_unique"


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0128_geocustomzone_import_layer_name"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
                        "ON core_detection (batch_id, import_id) "
                        "WHERE import_id IS NOT NULL"
                    ),
                    reverse_sql=f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}",
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="detection",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("import_id__isnull", False)),
                        fields=("batch_id", "import_id"),
                        name=INDEX_NAME,
                    ),
                ),
            ],
        ),
    ]
