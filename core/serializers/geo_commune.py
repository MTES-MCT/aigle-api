from core.models.geo_commune import GeoCommune
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework import serializers


class GeoCommuneSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoCommune
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "code",
        ]

    code = serializers.CharField(source="iso_code")


class GeoCommuneDetailSerializer(GeoCommuneSerializer):
    class Meta(GeoCommuneSerializer.Meta):
        fields = GeoCommuneSerializer.Meta.fields + [
            "geometry",
        ]
