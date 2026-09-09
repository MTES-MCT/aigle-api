from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from rest_framework import exceptions, serializers, status
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from core.models.user import UserRole
from core.services.mfa import MfaPolicy, MfaService


class LoginErrorCode:
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"
    ACCOUNT_DEACTIVATED = "ACCOUNT_DEACTIVATED"


class LoginError(exceptions.APIException):
    # Not a ValidationError: is_valid() would wrap "code" into a list.
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, code: str):
        super().__init__(detail={"non_field_errors": [message], "code": code})


def validate_login_user(user) -> None:
    if not user:
        raise LoginError(
            "Aucun compte actif trouvé avec ces identifiants.",
            LoginErrorCode.INVALID_CREDENTIALS,
        )
    if not user.is_active:
        raise LoginError("Ce compte est inactif.", LoginErrorCode.ACCOUNT_INACTIVE)
    if user.user_role == UserRole.DEACTIVATED:
        raise LoginError(
            "Votre compte est désactivé.", LoginErrorCode.ACCOUNT_DEACTIVATED
        )


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        if email is None:
            email = attrs.get(self.username_field)

        user = authenticate(email=email, password=password)
        validate_login_user(user)

        if MfaPolicy.is_required_for(user):
            # Aucun jeton tant que le second facteur n'est pas prouvé : le mot de
            # passe seul ne doit rien ouvrir.
            MfaService.send_login_link(user)
            return {"mfa_required": True}

        return super().validate(attrs)


class MfaVerifyLinkSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = MfaService.resolve_link(attrs["token"])

        if user is None:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "Ce lien de connexion est invalide ou a expiré. "
                        "Veuillez vous reconnecter pour en recevoir un nouveau."
                    ]
                }
            )

        refresh = RefreshToken.for_user(user)

        # SIMPLE_JWT.UPDATE_LAST_LOGIN n'agit que dans le chemin natif de simplejwt,
        # que cette vue court-circuite.
        update_last_login(None, user)

        return {"access": str(refresh.access_token), "refresh": str(refresh)}
