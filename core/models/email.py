from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH


from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from django.contrib.postgres.fields import ArrayField


class EmailType(models.TextChoices):
    CONTACT_US = "CONTACT_US", "CONTACT_US"


class Email(TimestampedModelMixin, UuidModelMixin):
    created_at = models.DateTimeField(auto_now_add=True)
    email_type = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=EmailType.choices,
    )

    subject = models.TextField()
    message = models.TextField()
    from_email = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    recipient_list = ArrayField(
        models.CharField(
            max_length=DEFAULT_MAX_LENGTH,
        )
    )
