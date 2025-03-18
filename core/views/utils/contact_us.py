from django.conf import settings
from django.http import HttpResponse

from rest_framework import serializers


from common.constants.models import DEFAULT_MAX_LENGTH
from django.core.mail import send_mail
from django.db import models
from rest_framework.status import HTTP_200_OK


class ContactReason(models.TextChoices):
    DEMO = "DEMO", "DEMO"
    BASIC = "BASIC", "BASIC"


class EndpointSerializer(serializers.Serializer):
    firstName = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    lastName = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    collectivity = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    job = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    phone = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    email = serializers.EmailField()
    contactReason = serializers.ChoiceField(
        choices=ContactReason.choices,
        default=ContactReason.BASIC,
    )


def endpoint(request):
    params_serializer = EndpointSerializer(data=request.GET)
    params_serializer.is_valid(raise_exception=True)

    send_mail(
        subject=f"[{params_serializer.data["contactReason"]}] Demande de contact",
        message=f"""Une demande de contact vient d'être envoyée:
- Nom : {params_serializer.data["lastName"]}
- Prénom : {params_serializer.data["firstName"]}
- Collectivité : {params_serializer.data["collectivity"]}
- Poste : {params_serializer.data["job"]}
- Téléphone : {params_serializer.data["phone"]}
- Adresse e-mail : {params_serializer.data["email"]}
        """,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[settings.EMAIL_HOST_USER],
        fail_silently=False,
    )

    return HttpResponse(status=HTTP_200_OK)


URL = "contact-us/"
