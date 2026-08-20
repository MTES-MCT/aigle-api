# Feature flags are a set, not a list, but Postgres has no set type and a CHECK
# constraint may not hold the subquery the de-duplication needs. The comparison
# therefore lives in an IMMUTABLE SQL function, which the constraint calls.
import common.models.functions
import django.contrib.postgres.fields
from django.db import migrations, models

ARRAY_HAS_UNIQUE_VALUES_SQL = """
    CREATE OR REPLACE FUNCTION array_has_unique_values(anyarray)
    RETURNS boolean
    LANGUAGE sql
    IMMUTABLE
    PARALLEL SAFE
    AS $$
        SELECT cardinality($1) = cardinality(ARRAY(SELECT DISTINCT unnest($1)))
    $$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0132_geocustomzonecategory_description"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ARRAY_HAS_UNIQUE_VALUES_SQL,
            reverse_sql="DROP FUNCTION IF EXISTS array_has_unique_values(anyarray);",
        ),
        migrations.AddField(
            model_name="usergroup",
            name="feature_flags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(
                    choices=[("STATS", "Statistiques")], max_length=255
                ),
                blank=True,
                default=list,
                size=None,
            ),
        ),
        # Django always drops the DEFAULT it used to backfill the column, which leaves
        # every raw-SQL writer (scripts/seed_data.sql, aigle-utils/sql_scripts) inserting
        # NULL into a NOT NULL column. Put it back: the ORM never reads it, those do.
        migrations.RunSQL(
            sql="ALTER TABLE core_usergroup ALTER COLUMN feature_flags SET DEFAULT '{}';",
            reverse_sql="ALTER TABLE core_usergroup ALTER COLUMN feature_flags DROP DEFAULT;",
        ),
        migrations.AddConstraint(
            model_name="usergroup",
            constraint=models.CheckConstraint(
                check=models.Q(
                    common.models.functions.ArrayHasUniqueValues("feature_flags")
                ),
                name="user_group_feature_flags_unique",
            ),
        ),
    ]
