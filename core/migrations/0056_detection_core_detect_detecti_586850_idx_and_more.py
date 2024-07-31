# Generated by Django 5.0.6 on 2024-07-19 10:12

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0055_remove_objecttypecategory_object_types_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="detection",
            index=models.Index(
                fields=["detection_object", "detection_data", "tile_set"],
                name="core_detect_detecti_586850_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="detectiondata",
            index=models.Index(
                fields=["detection_validation_status"],
                name="core_detect_detecti_d931b4_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="detectiondata",
            index=models.Index(
                fields=["detection_control_status"],
                name="core_detect_detecti_de016d_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="detectiondata",
            index=models.Index(
                fields=["detection_validation_status", "detection_control_status"],
                name="core_detect_detecti_e3c056_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="objecttype",
            index=models.Index(fields=["uuid"], name="core_object_uuid_e9c1f7_idx"),
        ),
        migrations.AddIndex(
            model_name="tileset",
            index=models.Index(
                fields=["tile_set_status", "date"],
                name="core_tilese_tile_se_59c3e2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="tileset",
            index=models.Index(fields=["uuid"], name="core_tilese_uuid_322dea_idx"),
        ),
    ]