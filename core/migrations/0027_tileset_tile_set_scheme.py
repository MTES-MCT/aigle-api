# Generated by Django 5.0.6 on 2024-06-14 11:16

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0026_rename_user_last_update_user_detectiondata_user_last_update"),
    ]

    operations = [
        migrations.AddField(
            model_name="tileset",
            name="tile_set_scheme",
            field=models.CharField(
                choices=[("tms", "tms"), ("xyz", "xyz")], default="tms", max_length=255
            ),
            preserve_default=False,
        ),
    ]
