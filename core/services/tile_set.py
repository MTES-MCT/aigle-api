from typing import Optional, List

from core.models.tile_set import TileSet, TileSetType
from core.permissions.tile_set import TileSetPermission
from django.contrib.gis.geos import Point


class TileSetService:
    """Service for handling TileSet business logic."""

    @staticmethod
    def find_tile_set_by_coordinates(
        x: float, y: float, user, tile_set_types: Optional[List[TileSetType]] = None
    ) -> Optional[TileSet]:
        """Find the appropriate tile set for given coordinates with user permissions."""
        point = Point(x, y)

        return (
            TileSetPermission(user=user)
            .filter_(
                filter_tile_set_type_in=tile_set_types,
                order_bys=["-date"],
                filter_tile_set_intersects_geometry=point,
            )
            .first()
        )
