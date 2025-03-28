# Generated by Django 5.0.6 on 2024-06-03 09:40

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_remove_objecttype_display_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="ObjectTypeCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("deleted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("name", models.CharField(max_length=255, unique=True)),
                (
                    "object_types",
                    models.ManyToManyField(
                        related_name="categories", to="core.objecttype"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
