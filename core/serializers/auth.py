from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from core.models.user import UserRole
from core.services.mfa import MfaPolicy, MfaService


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        if email is None:
            email = attrs.get(self.username_field)

        user = authenticate(email=email, password=password)

        if not user:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "Aucun compte actif trouvé avec ces identifiants."
                    ]
                }
            )
        if user and not user.is_active:
            raise serializers.ValidationError(
                {"non_field_errors": ["Ce compte est inactif."]}
            )
        if user and user.user_role == UserRole.DEACTIVATED:
            raise serializers.ValidationError(
                {"non_field_errors": ["Votre compte est désactivé."]}
            )

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
