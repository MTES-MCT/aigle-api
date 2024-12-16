from typing import Optional
from djoser.serializers import UserSerializer as UserSerializerBase
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from rest_framework import serializers

from core.models.user import UserRole
from core.models.user_group import UserGroup, UserUserGroup

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
        check_email_exists(email=validated_data["email"])

        if (
            self.context["request"].user.user_role != UserRole.SUPER_ADMIN
            and validated_data["user_role"] != UserRole.REGULAR
        ):
            raise PermissionDenied(
                "Un administrateur peut seulement créer des utilisateurs de rôle normal"
            )

        instance = UserModel.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            user_role=validated_data["user_role"],
        )

        return self.update(instance=instance, validated_data=validated_data)

    def update(self, instance, validated_data):
        if validated_data.get("email") and instance.email != validated_data["email"]:
            check_email_exists(email=validated_data["email"])

        password_clear = validated_data.pop("password", None)

        if password_clear:
            instance.set_password(password_clear)

        # if a user not super admin update a user other than him, he cannot

        if (
            self.context["request"].user.user_role != UserRole.SUPER_ADMIN
            and instance.id != self.context["request"].user.id
            and validated_data["user_role"] != UserRole.REGULAR
        ):
            raise PermissionDenied(
                "Un administrateur ne peut pas donner à un autre utilisateur un rôle autre que normal"
            )

        # if a user is not a super admin, he cannot set himself as super admin

        if (
            self.context["request"].user.user_role != UserRole.SUPER_ADMIN
            and validated_data["user_role"] == UserRole.SUPER_ADMIN
        ):
            raise PermissionDenied(
                "Un administrateur ne peut pas donner à un autre utilisateur le rôle de super administrateur"
            )

        # user_user_groups

        user_user_groups = validated_data.pop("user_user_groups", None)

        if user_user_groups is not None:
            user_user_groups_map = {
                user_user_group["user_group_uuid"]: user_user_group
                for user_user_group in user_user_groups
            }

            updated_groups = []

            for user_user_group in instance.user_user_groups.all():
                # update existing relationships
                if user_user_groups_map.get(user_user_group.user_group.uuid):
                    user_user_group.user_group_rights = user_user_groups_map[
                        user_user_group.user_group.uuid
                    ]["user_group_rights"]
                    updated_groups.append(user_user_group)
                    user_user_groups_map.pop(user_user_group.user_group.uuid)
                # remove deleted relationships
                else:
                    user_user_group.delete()

            if updated_groups:
                UserUserGroup.objects.bulk_update(updated_groups, ["user_group_rights"])

            # create newly created relationships
            new_groups = UserGroup.objects.filter(
                uuid__in=user_user_groups_map.keys()
            ).all()

            new_user_user_groups = []

            for new_group in new_groups:
                new_user_user_groups.append(
                    UserUserGroup(
                        user_group_rights=user_user_groups_map[new_group.uuid][
                            "user_group_rights"
                        ],
                        user=instance,
                        user_group=new_group,
                    )
                )

            UserUserGroup.objects.bulk_create(new_user_user_groups)

        for key, value in validated_data.items():
            setattr(instance, key, value)

        instance.save()

        return instance


def check_email_exists(email: str, uuid: Optional[str] = None):
    query = UserModel.objects.filter(
        email=email,
    )

    if query.exists():
        raise serializers.ValidationError(
            {"email": ["Un utilisateur avec cet email existe déjà"]}
        )
