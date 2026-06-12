from django.db import migrations

# Placeholder written in place of any cleartext secret found in existing
# UserActionLog.data rows. Kept self-contained (not imported from app code) so
# this migration's behaviour never changes if the runtime helper evolves.
REDACTED_PLACEHOLDER = "[REDACTED]"


def _is_sensitive_key(key):
    return isinstance(key, str) and "password" in key.lower()


def _redact_sensitive(value):
    if isinstance(value, dict):
        return {
            key: REDACTED_PLACEHOLDER
            if _is_sensitive_key(key)
            else _redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def redact_passwords(apps, schema_editor):
    UserActionLog = apps.get_model("core", "UserActionLog")

    batch = []
    queryset = (
        UserActionLog.objects.exclude(data__isnull=True)
        .only("id", "data")
        .iterator(chunk_size=500)
    )
    for log in queryset:
        redacted = _redact_sensitive(log.data)
        if redacted != log.data:
            log.data = redacted
            batch.append(log)
        if len(batch) >= 500:
            UserActionLog.objects.bulk_update(batch, ["data"])
            batch = []

    if batch:
        UserActionLog.objects.bulk_update(batch, ["data"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0117_alter_tileset_date_to_datefield"),
    ]

    operations = [
        # Irreversible by design: cleartext secrets cannot (and must not) be
        # restored, so the reverse is a no-op.
        migrations.RunPython(redact_passwords, migrations.RunPython.noop),
    ]
