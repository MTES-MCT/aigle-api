from django.db.models import Case, When, Value

from core.models.geo_custom_zone import GeoCustomZoneStatus
from core.models.tile_set import TileSetType

TILE_SETS_ORDER_BYS = [
    Case(
        When(tile_set_type=TileSetType.INDICATIVE, then=Value(0)),
        When(tile_set_type=TileSetType.PARTIAL, then=Value(1)),
        When(tile_set_type=TileSetType.BACKGROUND, then=Value(2)),
    ),
    "-date",
]

GEO_CUSTOM_ZONES_ORDER_BYS = [
    Case(
        When(geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE, then=Value(0)),
        When(geo_custom_zone_status=GeoCustomZoneStatus.INACTIVE, then=Value(1)),
    ),
    "name",
]
