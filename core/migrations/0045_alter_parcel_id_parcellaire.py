# Generated by Django 5.0.6 on 2024-07-09 12:33

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0044_remove_parcel_num_section_parcel_arpente_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="parcel",
            name="id_parcellaire",
            field=models.CharField(unique=True),
        ),
    ]
