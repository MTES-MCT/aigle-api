# Generated by Django 5.0.6 on 2025-06-17 13:09

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0101_alter_analyticlog_analytic_log_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommandRun",
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
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("command_name", models.CharField(max_length=255)),
                ("task_id", models.CharField(max_length=255, unique=True)),
                ("arguments", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("RUNNING", "Running"),
                            ("SUCCESS", "Success"),
                            ("ERROR", "Error"),
                        ],
                        default="PENDING",
                        max_length=255,
                    ),
                ),
                ("output", models.TextField(blank=True, null=True)),
                ("error", models.TextField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["task_id"], name="core_comman_task_id_bb1b6e_idx"
                    ),
                    models.Index(
                        fields=["status"], name="core_comman_status_e185b2_idx"
                    ),
                    models.Index(
                        fields=["command_name"], name="core_comman_command_31b56b_idx"
                    ),
                    models.Index(
                        fields=["created_at"], name="core_comman_created_3f3fc7_idx"
                    ),
                    models.Index(
                        fields=["status", "created_at"],
                        name="core_comman_status_0d4d81_idx",
                    ),
                ],
            },
        ),
    ]
