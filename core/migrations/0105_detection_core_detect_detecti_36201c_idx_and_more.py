# Generated by Django 5.0.6 on 2025-07-15 10:33

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0104_alter_commandrun_status_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="detection",
            index=models.Index(
                fields=["detection_object", "score", "detection_source"],
                name="core_detect_detecti_36201c_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="detectionobject",
            index=models.Index(
                fields=["object_type", "parcel"], name="core_detect_object__5c0631_idx"
            ),
        ),
    ]
