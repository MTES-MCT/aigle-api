from rest_framework import serializers


class RunCommandSerializer(serializers.Serializer):
    command = serializers.CharField(max_length=100, required=True)
    args = serializers.DictField(required=False, default=dict)

    def validate_command(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Command name cannot be empty")
        return value.strip()


class TaskStatusSerializer(serializers.Serializer):
    task_id = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    result = serializers.JSONField(read_only=True, allow_null=True)
    traceback = serializers.CharField(read_only=True, allow_null=True)


class CancelTaskSerializer(serializers.Serializer):
    task_id = serializers.CharField(required=True)

    def validate_task_id(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Task ID cannot be empty")
        return value.strip()


class TaskSerializer(serializers.Serializer):
    task_id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    args = serializers.ListField(read_only=True)
    kwargs = serializers.DictField(read_only=True)
    worker = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    eta = serializers.CharField(read_only=True, required=False, allow_null=True)
    time_start = serializers.CharField(read_only=True, required=False, allow_null=True)
    priority = serializers.IntegerField(read_only=True, required=False, allow_null=True)
