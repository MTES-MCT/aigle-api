import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0135_remove_mfa_login_link"),
        ("core", "0135_remove_stats_feature_flag"),
    ]

    # Both branches alter feature_flags' choices, and the graph may apply either one last:
    # pin the final state (no flag left). Choices only, no SQL.
    operations = [
        migrations.AlterField(
            model_name="usergroup",
            name="feature_flags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(choices=[], max_length=255),
                blank=True,
                default=list,
                size=None,
            ),
        ),
    ]
