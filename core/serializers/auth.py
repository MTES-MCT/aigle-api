from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from djoser.serializers import TokenCreateSerializer

from core.models.user import UserRole


class CustomTokenCreateSerializer(TokenCreateSerializer):
    def validate(self, attrs):
        password = attrs.get("password")
        params = {self.username_field: attrs.get(self.username_field)}
        self.user = authenticate(
            request=self.context.get("request"), **params, password=password
        )
        if not self.user:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "Aucun compte actif trouvé avec ces identifiants."
                    ]
                }
            )
        if self.user and not self.user.is_active:
            raise serializers.ValidationError(
                {"non_field_errors": ["Ce compte est inactif."]}
            )
        if self.user and self.user.user_role == UserRole.DEACTIVATED:
            raise serializers.ValidationError(
                {"non_field_errors": ["Votre compte est désactivé."]}
            )
        return attrs


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
