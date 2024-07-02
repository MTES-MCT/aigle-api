# Generated by Django 5.0.6 on 2024-07-01 09:10

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0038_geozone_name_normalized"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tileset",
            name="communes",
        ),
        migrations.RemoveField(
            model_name="tileset",
            name="departments",
        ),
        migrations.RemoveField(
            model_name="tileset",
            name="regions",
        ),
        migrations.RemoveField(
            model_name="usergroup",
            name="communes",
        ),
        migrations.RemoveField(
            model_name="usergroup",
            name="departments",
        ),
        migrations.RemoveField(
            model_name="usergroup",
            name="regions",
        ),
        migrations.AddField(
            model_name="tileset",
            name="geo_zones",
            field=models.ManyToManyField(related_name="tile_sets", to="core.geozone"),
        ),
        migrations.AddField(
            model_name="usergroup",
            name="geo_zones",
            field=models.ManyToManyField(related_name="user_groups", to="core.geozone"),
        ),
    ]