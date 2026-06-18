from rest_framework import serializers

from core.models.command_run import CommandRun, CommandRunStatus
from core.serializers import UuidTimestampedModelSerializerMixin
from core.utils.command_progress import get_command_progress


class CommandRunSerializer(UuidTimestampedModelSerializerMixin):
    # Ephemeral progress lives in Redis, not the DB. The list view bulk-loads it into
    # context["command_progress_map"]; a missing map (single-object use) falls back to a
    # direct lookup. Either way: {"current", "total"} while running, else null.
    progress = serializers.SerializerMethodField()

    class Meta:
        model = CommandRun
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "command_name",
            "arguments",
            "task_id",
            "run_origin",
            "status",
            "run_started_at",
            "run_ended_at",
            "progress",
            "created_at",
            "updated_at",
            "error",
            "output",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_progress(self, obj):
        # Progress is meaningful only while a run is active. A finished/cancelled run must
        # never render a bar — even if its Redis key briefly outlives it (the cancel-path
        # clear races the worker's last batch; both are reaped by the TTL backstop).
        if obj.is_finished():
            return None
        progress_map = self.context.get("command_progress_map")
        if progress_map is not None:
            return progress_map.get(obj.pk)
        return get_command_progress(obj.pk)


class ListTasksParametersSerializer(serializers.Serializer):
    statuses = serializers.CharField(required=False, allow_blank=True)
    q = serializers.CharField(required=False, allow_blank=True)

    def validate_q(self, value):
        return value.strip() or None

    def validate_statuses(self, value):
        if not value:
            return None

        status_strings = [s.strip().upper() for s in value.split(",") if s.strip()]

        valid_statuses = [choice[0] for choice in CommandRunStatus.choices]
        invalid_statuses = [s for s in status_strings if s not in valid_statuses]

        if invalid_statuses:
            raise serializers.ValidationError(
                f"Invalid status(es): {', '.join(invalid_statuses)}. "
                f"Valid statuses are: {', '.join(valid_statuses)}"
            )

        return [CommandRunStatus(s) for s in status_strings]
