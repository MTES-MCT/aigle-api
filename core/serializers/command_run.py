from rest_framework import serializers

from core.models.command_run import CommandRun, CommandRunStatus
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


class ListTasksParametersSerializer(serializers.Serializer):
    statuses = serializers.CharField(required=False, allow_blank=True)

    def validate_statuses(self, value):
        if not value:
            return None

        # Split by comma and clean up
        status_strings = [s.strip().upper() for s in value.split(",") if s.strip()]

        # Validate each status
        valid_statuses = [choice[0] for choice in CommandRunStatus.choices]
        invalid_statuses = [s for s in status_strings if s not in valid_statuses]

        if invalid_statuses:
            raise serializers.ValidationError(
                f"Invalid status(es): {', '.join(invalid_statuses)}. "
                f"Valid statuses are: {', '.join(valid_statuses)}"
            )

        # Return list of CommandRunStatus enum values
        return [CommandRunStatus(s) for s in status_strings]
