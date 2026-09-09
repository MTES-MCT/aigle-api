import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.exceptions import APIException, Throttled

from core.models.email import EmailType
from core.models.user import UserRole
from core.models.user_group import FeatureFlag, UserGroup
from core.utils import mfa_challenge
from core.utils.email import send_mail
from core.utils.string import strip_email_subaddress

UserModel = get_user_model()
logger = logging.getLogger("aigle")

EMAIL_SUBJECT = "Aigle - votre lien de connexion"
EMAIL_BODY = """Bonjour,

Une connexion à Aigle vient d'être demandée pour le compte {account}.

Pour la valider, ouvrez ce lien dans les {minutes} minutes :

{link}

Ce lien est à usage unique.

Si vous n'êtes pas à l'origine de cette demande, ignorez ce message et changez
votre mot de passe : quelqu'un connaît vos identifiants.

L'équipe Aigle
"""

# core_email conserve le corps des messages : un lien de connexion est une
# crédential vivante, on garde la trace de l'envoi mais jamais le secret.
STORED_MESSAGE = "[lien de connexion expurgé]"


class MfaUnavailable(APIException):
    status_code = 503
    default_detail = (
        "Le service d'authentification est momentanément indisponible. "
        "Veuillez réessayer dans quelques instants."
    )


class MfaPolicy:
    @staticmethod
    def is_required_for(user) -> bool:
        if not settings.MFA_ENABLED:
            return False

        if user.user_role in (UserRole.SUPER_ADMIN, UserRole.ADMIN):
            return True

        return UserGroup.objects.filter(
            user_user_groups__user=user,
            feature_flags__contains=[FeatureFlag.REQUIRE_2FA],
        ).exists()


class MfaService:
    @staticmethod
    def send_login_link(user) -> None:
        """Crée le défi et envoie le lien. Lève une APIException si l'un des deux échoue."""
        try:
            mfa_challenge.check_quota(user.id)
            token = mfa_challenge.create(user.id)
        except mfa_challenge.MfaChallengeQuotaExceeded:
            raise Throttled(
                detail=(
                    "Trop de demandes de connexion pour ce compte. "
                    "Veuillez réessayer dans une heure."
                )
            )
        except mfa_challenge.MfaChallengeUnavailable:
            raise MfaUnavailable()

        try:
            send_mail(
                subject=EMAIL_SUBJECT,
                message=EMAIL_BODY.format(
                    account=user.email,
                    link=f"{settings.MFA_LOGIN_LINK_BASE_URL}{token}",
                    minutes=mfa_challenge.CHALLENGE_TTL_SECONDS // 60,
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                # Plusieurs comptes sous-adressés partagent une seule boîte : c'est
                # pour cela que le corps du message rappelle le compte concerné.
                recipient_list=[strip_email_subaddress(user.email)],
                email_type=EmailType.MFA_LOGIN_LINK,
                stored_message=STORED_MESSAGE,
            )
        except Exception:
            # Sans courriel délivré le défi est inutilisable : le dire plutôt que
            # de laisser l'utilisateur attendre un message qui n'arrivera pas.
            logger.exception("mfa: envoi du lien de connexion impossible")
            raise MfaUnavailable()

        # Après l'envoi seulement : une panne SMTP ne doit pas épuiser le quota du
        # compte et le verrouiller une heure alors qu'aucun lien n'a été délivré.
        mfa_challenge.register_sent(user.id)

    @staticmethod
    def resolve_link(token: str):
        """Consomme le jeton et rend l'utilisateur, ou None si le lien ne vaut plus rien."""
        try:
            user_id = mfa_challenge.consume(token)
        except mfa_challenge.MfaChallengeUnavailable:
            raise MfaUnavailable()

        if user_id is None:
            return None

        # Le compte a pu être désactivé entre l'envoi du lien et son ouverture.
        user = UserModel.objects.filter(id=user_id).first()
        if user is None or not user.is_active or user.user_role == UserRole.DEACTIVATED:
            return None

        return user
