from django.db import migrations, models


CONTROL_STATUS_CHOICES = [
    ("NOT_CONTROLLED", "NOT_CONTROLLED"),
    ("TO_CONTROL", "TO_CONTROL"),
    ("CONTROLLED_FIELD", "CONTROLLED_FIELD"),
    ("PRIOR_LETTER_SENT", "PRIOR_LETTER_SENT"),
    ("OFFICIAL_REPORT_DRAWN_UP", "OFFICIAL_REPORT_DRAWN_UP"),
    ("OBSERVARTION_REPORT_REDACTED", "OBSERVARTION_REPORT_REDACTED"),
    ("ADMINISTRATIVE_CONSTRAINT", "ADMINISTRATIVE_CONSTRAINT"),
    ("JUGEMENT", "JUGEMENT"),
    ("REHABILITATED", "REHABILITATED"),
]

VALIDATION_STATUS_CHOICES = [
    ("DETECTED_NOT_VERIFIED", "DETECTED_NOT_VERIFIED"),
    ("SUSPECT", "SUSPECT"),
    ("ILLEGAL", "ILLEGAL"),
    ("LEGITIMATE", "LEGITIMATE"),
    ("INVALIDATED", "INVALIDATED"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0125_remove_unused_indexes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="detectiondata",
            name="detection_control_status",
            field=models.CharField(choices=CONTROL_STATUS_CHOICES, max_length=255),
        ),
        migrations.AlterField(
            model_name="historicaldetectiondata",
            name="detection_control_status",
            field=models.CharField(choices=CONTROL_STATUS_CHOICES, max_length=255),
        ),
        migrations.AlterField(
            model_name="detectiondata",
            name="detection_validation_status",
            field=models.CharField(choices=VALIDATION_STATUS_CHOICES, max_length=255),
        ),
        migrations.AlterField(
            model_name="historicaldetectiondata",
            name="detection_validation_status",
            field=models.CharField(choices=VALIDATION_STATUS_CHOICES, max_length=255),
        ),
    ]
