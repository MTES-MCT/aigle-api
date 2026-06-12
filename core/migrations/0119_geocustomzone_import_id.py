from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0118_redact_user_action_log_passwords"),
    ]

    operations = [
        migrations.AddField(
            model_name="geocustomzone",
            name="import_id",
            field=models.BigIntegerField(null=True),
        ),
    ]
