# Generated by Django 5.0.6 on 2025-05-28 12:32

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0099_geocommune_epci_alter_geozone_geo_zone_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="geocustomzone",
            name="name_short",
            field=models.CharField(max_length=255, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="geocustomzonecategory",
            name="name_short",
            field=models.CharField(max_length=255, null=True, unique=True),
        ),
    ]
