# Generated by Django 5.0.6 on 2025-01-03 15:47

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0077_historicaluser"),
    ]

    operations = [
        migrations.AlterField(
            model_name="analyticlog",
            name="analytic_log_type",
            field=models.CharField(
                choices=[
                    ("REPORT_DOWNLOAD", "REPORT_DOWNLOAD"),
                    ("USER_ACCESS", "USER_ACCESS"),
                ],
                max_length=255,
            ),
        ),
        migrations.AddIndex(
            model_name="detection",
            index=models.Index(fields=["id"], name="core_detect_id_184630_idx"),
        ),
        migrations.AddIndex(
            model_name="detection",
            index=models.Index(
                fields=["detection_data"], name="core_detect_detecti_6048d4_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="detection",
            index=models.Index(
                fields=["detection_object"], name="core_detect_detecti_210b06_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="detectionobject",
            index=models.Index(
                fields=["object_type"], name="core_detect_object__7e35ba_idx"
            ),
        ),
    ]
