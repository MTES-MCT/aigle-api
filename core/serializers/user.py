from djoser.serializers import UserSerializer as UserSerializerBase
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from rest_framework import serializers

UserModel = get_user_model()


class UserSerializer(UserSerializerBase):
    from core.serializers.user_group import UserUserGroupSerializer

    class Meta(UserSerializerBase.Meta):
        model = UserModel
        fields = [
            "uuid",
            "created_at",
            "updated_at",
            "email",
            "user_role",
            "deleted",
            "user_user_groups",
        ]

    email = serializers.CharField()
    user_user_groups = UserUserGroupSerializer(many=True)


class UserInputSerializer(UserSerializer):
    from core.serializers.user_group import UserUserGroupInputSerializer

    class Meta(UserSerializer.Meta):
        fields = ["email", "user_role", "deleted", "password", "user_user_groups"]

    password = serializers.CharField()
    user_user_groups = UserUserGroupInputSerializer(many=True)

    def create(self, validated_data):
        from core.services.user import UserService

        user_user_groups = validated_data.pop("user_user_groups", None)
        password = validated_data.pop("password")

        try:
            return UserService.create_user(
                email=validated_data["email"],
                password=password,
                user_role=validated_data["user_role"],
                requesting_user=self.context["request"].user,
                user_user_groups=user_user_groups,
            )
        except serializers.ValidationError:
            raise

    def update(self, instance, validated_data):
        from core.services.user import UserService

        user_user_groups = validated_data.pop("user_user_groups", None)
        password = validated_data.pop("password", None)

        try:
            return UserService.update_user(
                user=instance,
                requesting_user=self.context["request"].user,
                email=validated_data.get("email"),
                password=password,
                user_role=validated_data.get("user_role"),
                user_user_groups=user_user_groups,
                **{
                    k: v
                    for k, v in validated_data.items()
                    if k not in ["email", "user_role"]
                },
            )
        except (serializers.ValidationError, PermissionDenied):
            raise
