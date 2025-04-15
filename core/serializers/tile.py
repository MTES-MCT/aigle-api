from core.models.tile import Tile
from rest_framework import serializers


class TileMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tile
        fields = ["x", "y", "z"]


class TileSerializer(TileMinimalSerializer):
    class Meta(TileMinimalSerializer.Meta):
        fields = TileMinimalSerializer.Meta.fields + ["geometry"]
