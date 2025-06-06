# Generated by Django 5.0.6 on 2024-10-18 08:33

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0070_alter_detectiondata_detection_control_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="usergroup",
            name="user_group_type",
            field=models.CharField(
                choices=[("DDTM", "DDTM"), ("COLLECTIVITY", "COLLECTIVITY")],
                default="COLLECTIVITY",
                max_length=255,
            ),
            preserve_default=False,
        ),
    ]
