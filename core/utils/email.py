from typing import List
from django.core.mail import send_mail as send_mail_

from core.models.email import Email, EmailType


def send_mail(
    subject: str,
    message: str,
    from_email: str,
    recipient_list: List[str],
    email_type: EmailType,
):
    Email(
        email_type=email_type,
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=recipient_list,
    ).save()
    send_mail_(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=recipient_list,
    )
