# Generated by Django 5.0.6 on 2025-05-20 13:11

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0095_detectionobject_commune_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="geozone",
            name="geo_zone_type",
            field=models.CharField(
                choices=[
                    ("COMMUNE", "COMMUNE"),
                    ("DEPARTMENT", "DEPARTMENT"),
                    ("REGION", "REGION"),
                    ("CUSTOM", "CUSTOM"),
                    ("SUB_CUSTOM", "SUB_CUSTOM"),
                ],
                editable=False,
                max_length=255,
            ),
        ),
        migrations.CreateModel(
            name="GeoSubCustomZone",
            fields=[
                (
                    "geozone_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="core.geozone",
                    ),
                ),
                (
                    "custom_zone",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sub_custom_zones",
                        to="core.geocustomzone",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["geozone_ptr"], name="core_geosub_geozone_7bdbef_idx"
                    )
                ],
            },
            bases=("core.geozone",),
        ),
    ]
