# Generated by Django 5.0.6 on 2024-05-29 13:14

from django.db import migrations
from django.contrib.postgres.operations import CreateExtension


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_user_created_at_user_deleted_user_updated_at_and_more"),
    ]
    operations = [CreateExtension("postgis")]
