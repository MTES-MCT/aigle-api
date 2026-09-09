from typing import List, Optional
from django.core.mail import send_mail as send_mail_

from core.models.email import Email, EmailType


def send_mail(
    subject: str,
    message: str,
    from_email: str,
    recipient_list: List[str],
    email_type: EmailType,
    stored_message: Optional[str] = None,
):
    Email(
        email_type=email_type,
        subject=subject,
        # Le corps est conservé en base : un message qui transporte un secret passe
        # stored_message pour garder la trace de l'envoi sans le secret.
        message=stored_message if stored_message is not None else message,
        from_email=from_email,
        recipient_list=recipient_list,
    ).save()
    send_mail_(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=recipient_list,
    )
