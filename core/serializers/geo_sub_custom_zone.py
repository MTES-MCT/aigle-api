from core.models.geo_sub_custom_zone import GeoSubCustomZone
from core.serializers import UuidTimestampedModelSerializerMixin


class GeoSubCustomZoneMinimalSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoSubCustomZone
        fields = [
            "uuid",
            "name",
        ]
