# Generated by Django 5.0.6 on 2024-11-04 15:55

import datetime
import django.contrib.gis.db.models.fields
import django.db.models.deletion
import simple_history.models
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0076_analyticlog_data"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalUser",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                (
                    "last_login",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="last login"
                    ),
                ),
                (
                    "is_superuser",
                    models.BooleanField(
                        default=False,
                        help_text="Designates that this user has all permissions without explicitly assigning them.",
                        verbose_name="superuser status",
                    ),
                ),
                ("deleted", models.BooleanField(default=False)),
                ("deleted_at", models.DateTimeField(null=True)),
                ("created_at", models.DateTimeField(blank=True, editable=False)),
                ("updated_at", models.DateTimeField(blank=True, editable=False)),
                (
                    "uuid",
                    models.UUIDField(db_index=True, default=uuid.uuid4, editable=False),
                ),
                ("changed_fields", models.JSONField(blank=True, null=True)),
                ("email", models.EmailField(db_index=True, max_length=255)),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                (
                    "date_joined",
                    models.DateTimeField(
                        default=datetime.datetime.now, verbose_name="date joined"
                    ),
                ),
                (
                    "user_role",
                    models.CharField(
                        choices=[
                            ("SUPER_ADMIN", "SUPER_ADMIN"),
                            ("ADMIN", "ADMIN"),
                            ("REGULAR", "REGULAR"),
                        ],
                        default="REGULAR",
                        max_length=255,
                    ),
                ),
                (
                    "last_position",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, null=True, srid=4326
                    ),
                ),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical user",
                "verbose_name_plural": "historical users",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
    ]
