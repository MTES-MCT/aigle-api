from typing import Optional, List, Dict, Any, Tuple

from core.models.tile_set import TileSet, TileSetType
from core.permissions.user import UserPermission
from core.repository.tile_set import TileSetRepository
from core.repository.detection import DetectionRepository


class TileSetService:
    """Service for handling TileSet business logic."""

    @staticmethod
    def find_tile_set_by_coordinates(
        x: float, y: float, user, tile_set_types: Optional[List[TileSetType]] = None
    ) -> Optional[TileSet]:
        """Find the appropriate tile set for given coordinates with user permissions."""

        # Get user permissions and filter tile sets accordingly
        user_permission = UserPermission(user=user)
        collectivity_filter = user_permission.get_collectivity_filter()

        # Use repository with user permissions
        tile_set_repo = TileSetRepository()
        available_tile_sets = tile_set_repo.filter_(
            queryset=tile_set_repo.initial_queryset,
            filter_collectivities=collectivity_filter,
            filter_tile_set_type_in=tile_set_types,
        )

        # Find tile set containing the coordinates
        for tile_set in available_tile_sets:
            if (
                tile_set.x_min <= x <= tile_set.x_max
                and tile_set.y_min <= y <= tile_set.y_max
            ):
                return tile_set

        return None

    @staticmethod
    def generate_tile_set_preview(
        tile_set: TileSet, user, detection_limit: int = 100
    ) -> Dict[str, Any]:
        """Generate preview data for a tile set."""

        # Use repository to get filtered detections for preview
        detection_repo = DetectionRepository()
        detections = detection_repo.initial_queryset.filter(tile__tile_set=tile_set)[
            :detection_limit
        ]

        # Apply basic user filtering - you may need to customize this based on your permission logic
        # This replaces the non-existent filter_detections_for_user method
        filtered_detections = detections.filter(
            detection_object__user_groups__users=user
        ).distinct()

        return {
            "tile_set_id": tile_set.id,
            "detection_count": filtered_detections.count(),
            "detections": list(
                filtered_detections.values(
                    "id", "location", "detection_object__object_type__name"
                )
            ),
        }

    @staticmethod
    def calculate_tile_coordinates(
        x: float, y: float, tile_set: TileSet, user
    ) -> Tuple[int, int, int]:
        """Calculate tile coordinates (tile_x, tile_y, zoom) from geographic coordinates."""
        # Validate user has access to the tile set first
        if not TileSetService.validate_tile_access(
            tile_set=tile_set, user=user, x=x, y=y
        ):
            raise PermissionError(
                "User does not have access to this tile set or coordinates"
            )

        # This is a simplified version - actual implementation would depend on
        # the specific tile coordinate system used
        zoom_level = tile_set.max_zoom or 18

        # Convert geographic coordinates to tile coordinates
        # This is a placeholder - actual implementation would use proper tile math
        tile_x = int(
            (x - tile_set.x_min) / (tile_set.x_max - tile_set.x_min) * (2**zoom_level)
        )
        tile_y = int(
            (y - tile_set.y_min) / (tile_set.y_max - tile_set.y_min) * (2**zoom_level)
        )

        return tile_x, tile_y, zoom_level

    @staticmethod
    def validate_tile_access(
        tile_set: TileSet, user, x: Optional[float] = None, y: Optional[float] = None
    ) -> bool:
        """Validate if user has access to a tile set and optional coordinates."""
        # Use repository with user permissions to check access
        user_permission = UserPermission(user=user)
        collectivity_filter = user_permission.get_collectivity_filter()

        tile_set_repo = TileSetRepository()
        user_tile_sets = tile_set_repo.filter_(
            queryset=tile_set_repo.initial_queryset,
            filter_collectivities=collectivity_filter,
        )
        if not user_tile_sets.filter(id=tile_set.id).exists():
            return False

        # If coordinates provided, check if they're within bounds
        if x is not None and y is not None:
            return (
                tile_set.x_min <= x <= tile_set.x_max
                and tile_set.y_min <= y <= tile_set.y_max
            )

        return True
