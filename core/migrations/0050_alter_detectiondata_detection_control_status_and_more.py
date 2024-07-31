# Generated by Django 5.0.6 on 2024-07-17 08:43

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0049_objecttype_prescription_duration_years"),
    ]

    operations = [
        migrations.AlterField(
            model_name="detectiondata",
            name="detection_control_status",
            field=models.CharField(
                choices=[
                    ("NOT_CONTROLLED", "NOT_CONTROLLED"),
                    ("SIGNALED_INTERNALLY", "SIGNALED_INTERNALLY"),
                    ("SIGNALED_COLLECTIVITY", "SIGNALED_COLLECTIVITY"),
                    ("VERBALIZED", "VERBALIZED"),
                    ("REHABILITATED", "REHABILITATED"),
                ],
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="detectiondata",
            name="detection_validation_status",
            field=models.CharField(
                choices=[
                    ("DETECTED_NOT_VERIFIED", "DETECTED_NOT_VERIFIED"),
                    ("SUSPECT", "SUSPECT"),
                    ("LEGITIMATE", "LEGITIMATE"),
                    ("INVALIDATED", "INVALIDATED"),
                    ("DISAPPEARED", "DISAPPEARED"),
                ],
                max_length=255,
            ),
        ),
        migrations.AddIndex(
            model_name="parcel",
            index=models.Index(
                fields=["num_parcel"], name="core_parcel_num_par_2c6154_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="parcel",
            index=models.Index(
                fields=["section"], name="core_parcel_section_664616_idx"
            ),
        ),
    ]