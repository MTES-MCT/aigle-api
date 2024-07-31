# Generated by Django 5.0.6 on 2024-07-29 08:41

import django.contrib.gis.db.models.fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0060_user_last_position"),
    ]

    operations = [
        migrations.AlterField(
            model_name="geozone",
            name="geometry",
            field=django.contrib.gis.db.models.fields.GeometryField(
                null=True, srid=4326
            ),
        ),
    ]