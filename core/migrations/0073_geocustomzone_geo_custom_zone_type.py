# Generated by Django 5.0.6 on 2024-10-25 12:03

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0072_historicaldetection_historicaldetectiondata_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="geocustomzone",
            name="geo_custom_zone_type",
            field=models.CharField(
                choices=[
                    ("COMMON", "COMMON"),
                    ("COLLECTIVITY_MANAGED", "COLLECTIVITY_MANAGED"),
                ],
                default="COMMON",
                max_length=255,
            ),
        ),
    ]
