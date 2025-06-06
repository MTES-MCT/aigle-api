# Generated by Django 5.0.6 on 2024-11-04 14:55

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0074_historicaldetection_changed_fields_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnalyticLog",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "analytic_log_type",
                    models.CharField(
                        choices=[("REPORT_DOWNLOAD", "REPORT_DOWNLOAD")], max_length=255
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="analytic_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["created_at"], name="core_analyt_created_d7626f_idx"
                    ),
                    models.Index(
                        fields=["analytic_log_type"],
                        name="core_analyt_analyti_10dd91_idx",
                    ),
                    models.Index(
                        fields=["created_at", "analytic_log_type"],
                        name="core_analyt_created_6b9809_idx",
                    ),
                    models.Index(
                        fields=["user"], name="core_analyt_user_id_915201_idx"
                    ),
                ],
            },
        ),
    ]
