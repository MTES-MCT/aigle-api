from rest_framework import serializers


class RunCommandSerializer(serializers.Serializer):
    command = serializers.CharField(max_length=100, required=True)
    args = serializers.DictField(required=False, default=dict)

    def validate_command(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Command name cannot be empty")
        return value.strip()
