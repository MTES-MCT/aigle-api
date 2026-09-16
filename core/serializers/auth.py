from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from core.models.user import UserRole


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

        return super().validate(attrs)
