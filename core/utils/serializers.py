import uuid
from rest_framework import serializers


class CommaSeparatedUUIDField(serializers.Field):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError(
                "This field should be a string of comma-separated UUIDs."
            )

        uuid_list = data.split(",")

        # Validate each UUID
        for value in uuid_list:
            try:
                uuid.UUID(value)
            except ValueError:
                raise serializers.ValidationError(f"{value} is not a valid UUID.")

        return uuid_list

    def to_representation(self, value):
        if isinstance(value, list):
            return ",".join([str(v) for v in value])
        return value


class CommaSeparatedStringField(serializers.Field):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError(
                "This field should be a string of comma-separated strings."
            )

        strings_list = data.split(",")

        return strings_list

    def to_representation(self, value):
        if isinstance(value, list):
            return ",".join([str(v) for v in value])
        return value
