from core.models.geo_department import GeoDepartment
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework import serializers


class GeoDepartmentSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoDepartment
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "code",
            "surface_km2",
        ]

    code = serializers.CharField(source="insee_code")


class GeoDepartmentDetailSerializer(GeoDepartmentSerializer):
    class Meta(GeoDepartmentSerializer.Meta):
        fields = GeoDepartmentSerializer.Meta.fields + ["geometry"]
