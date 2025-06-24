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


class Criticity(models.TextChoices):
    CRITICAL = "CRITICAL", "Un problème critique"
    NORMAL = "NORMAL", "Un simple problème parmi d'autres"
    NON_EXISTENT = "NON_EXISTENT", "Pas un problème"


class Interest(models.TextChoices):
    RESOLVE_AN_ISSUE = (
        "RESOLVE_AN_ISSUE",
        "Aigle répond précisément à un problème que je rencontre",
    )
    UNKNOWN = (
        "UNKNOWN",
        "Je ne sais pas si Aigle m'intéresse, je cherche à comprendre à quoi ça sert",
    )


class EndpointSerializer(serializers.Serializer):
    criticity = serializers.ChoiceField(
        choices=Criticity.choices,
        default=Criticity.CRITICAL,
    )
    collectivity = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    interest = serializers.ChoiceField(
        choices=Interest.choices,
        default=Interest.RESOLVE_AN_ISSUE,
    )
    issue = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    name = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
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
- Collectivité : {params_serializer.data["collectivity"]}
- Criticité : {Criticity[params_serializer.data["criticity"]].label}
- Intérêt : {Interest[params_serializer.data["interest"]].label}
- Problème : {params_serializer.data["issue"]}
- Nom et prénom : {params_serializer.data["name"]}
- Fonction : {params_serializer.data["job"]}
- Téléphone : {params_serializer.data["phone"]}
- Adresse e-mail : {params_serializer.data["email"]}
        """,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[settings.EMAIL_HOST_USER],
        fail_silently=False,
    )

    return HttpResponse(status=HTTP_200_OK)


URL = "contact-us/"
