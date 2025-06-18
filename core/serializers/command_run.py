from core.models.command_run import CommandRun
from core.serializers import UuidTimestampedModelSerializerMixin


class CommandRunSerializer(UuidTimestampedModelSerializerMixin):
    class Meta:
        model = CommandRun
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "command_name",
            "arguments",
            "task_id",
            "status",
            "created_at",
            "updated_at",
            "error",
            "output",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
