from rest_framework import serializers

from core.models.user_action_log import UserActionLog
from core.serializers import UuidTimestampedModelSerializerMixin


class UserActionLogUserSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)


class UserActionLogSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = UserActionLog
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "route",
            "action",
            "data",
            "user",
        ]

    user = UserActionLogUserSerializer(read_only=True)
