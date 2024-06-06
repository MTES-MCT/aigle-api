# Generated by Django 5.0.6 on 2024-05-30 10:10

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_georegion_surface_km2"),
    ]

    operations = [
        migrations.AlterField(
            model_name="georegion",
            name="display_name",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.AlterField(
            model_name="georegion",
            name="iso_code",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.AlterField(
            model_name="georegion",
            name="name",
            field=models.CharField(max_length=255, unique=True),
        ),
    ]