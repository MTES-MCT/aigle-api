from rest_framework import serializers

from core.models.geo_zone import GeoZoneType


class UuidTimestampedModelSerializerMixin(serializers.ModelSerializer):
    class Meta:
        fields = [
            "uuid",
            "created_at",
            "updated_at",
        ]

    uuid = serializers.UUIDField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
