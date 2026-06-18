from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0126_add_illegal_and_to_control_statuses"),
    ]

    operations = [
        migrations.AddField(
            model_name="commandrun",
            name="run_origin",
            field=models.CharField(
                choices=[("API", "API"), ("CLI", "CLI")],
                default="API",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="commandrun",
            name="run_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="commandrun",
            name="run_ended_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
