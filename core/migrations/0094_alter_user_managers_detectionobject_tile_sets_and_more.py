# Generated by Django 5.0.6 on 2025-04-10 13:14

import core.models.user
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0093_create_views"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="user",
            managers=[
                ("objects", core.models.user.UserManager_()),
            ],
        ),
        migrations.AddField(
            model_name="detectionobject",
            name="tile_sets",
            field=models.ManyToManyField(through="core.Detection", to="core.tileset"),
        ),
        migrations.AlterField(
            model_name="parcel",
            name="num_parcel",
            field=models.IntegerField(max_length=255),
        ),
    ]
