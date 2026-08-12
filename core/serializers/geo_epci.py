from core.models.geo_epci import GeoEpci
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework import serializers


class GeoEpciSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoEpci
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "code",
        ]

    code = serializers.CharField(source="siren_code")


class GeoEpciDetailSerializer(GeoEpciSerializer):
    class Meta(GeoEpciSerializer.Meta):
        fields = GeoEpciSerializer.Meta.fields + ["geometry"]
