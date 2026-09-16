from django.contrib.auth import authenticate
from rest_framework import exceptions, status
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from core.models.user import UserRole


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

        return super().validate(attrs)
