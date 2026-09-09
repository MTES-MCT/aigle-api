from django.conf import settings

from rest_framework import serializers
from rest_framework.decorators import (
    api_view,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle


from common.constants.models import DEFAULT_MAX_LENGTH
from django.db import models
from rest_framework.status import HTTP_200_OK

from core.models.email import EmailType
from core.utils.email import send_mail


class ContactUsRateThrottle(SimpleRateThrottle):
    """Plafond dédié (DEFAULT_THROTTLE_RATES["contact"]) : chaque appel déclenche un
    envoi SMTP synchrone. Contrairement à AnonRateThrottle il s'applique aussi à un
    appelant authentifié, qui sinon échapperait au quota."""

    scope = "contact"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


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
    issue = serializers.CharField()
    name = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    job = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    phone = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    email = serializers.EmailField()
    contactReason = serializers.ChoiceField(
        choices=ContactReason.choices,
        default=ContactReason.BASIC,
    )


# Vue Django brute à l'origine (ni APIView ni @api_view) : elle échappait donc à
# DEFAULT_THROTTLE_CLASSES comme à DEFAULT_PERMISSION_CLASSES, soit un envoi de courriel
# non authentifié et sans plafond. Et c'était un GET, donc l'état civil, le téléphone et
# l'adresse du demandeur passaient en query string — journalisés par le proxy et l'API,
# conservés dans l'historique du navigateur. POST + corps de requête + quota dédié.
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ContactUsRateThrottle])
def endpoint(request):
    params_serializer = EndpointSerializer(data=request.data)
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
        email_type=EmailType.CONTACT_US,
    )

    return Response(status=HTTP_200_OK)


URL = "contact-us/"
