import json
from django.db import models
from django.db.models import JSONField

from simple_history.signals import pre_create_historical_record
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(pre_create_historical_record)
def track_changed_fields(sender, instance, history_instance, **kwargs):
    # Get current and previous historical records
    previous = instance.history.first()
    current = instance

    # Compare each field in your model to find changes
    changed_fields = []
    if previous:
        for field in instance._meta.fields:
            field_name = field.name
            current_value = getattr(current, field_name, None)
            previous_value = getattr(previous, field_name, None)

            if current_value != previous_value:
                changed_fields.append(
                    {
                        "field": field_name,
                        "old_value": previous_value,
                        "new_value": current_value,
                    }
                )

    # Save the changed fields to the history instance
    history_instance.changed_fields = json.loads(
        json.dumps(changed_fields, indent=4, sort_keys=True, default=str)
    )


@receiver(post_save)
def create_history_record_on_insert(sender, instance, created, **kwargs):
    if created and hasattr(instance, "history"):
        try:
            instance.history.create(history_type="+", history_user=None)
        except Exception:
            # Honestly I don't really know why it fails sometimes, it raises an integrity error
            pass


class HistoriedModelMixin(models.Model):
    changed_fields = JSONField(blank=True, null=True)

    class Meta:
        abstract = True
