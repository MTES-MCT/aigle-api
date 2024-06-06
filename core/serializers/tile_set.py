from core.models.tile_set import TileSet
from core.serializers import UuidTimestampedModelSerializerMixin


class TileSetSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = TileSet
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "url",
            "tile_set_status",
            "date",
        ]