from typing import Optional
from django.db.models import QuerySet

from core.models.detection_data import DetectionControlStatus, DetectionValidationStatus
from core.models.tile_set import TileSetType, TileSetStatus
from core.permissions.user import UserPermission
from core.permissions.tile_set import TileSetPermission
from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import RepoFilterCustomZone, RepoFilterInterfaceDrawn
from core.repository.parcel import DetectionFilter, ParcelRepository
from core.utils.string import to_array, to_bool, to_enum_array


class ParcelFilterService:
    """Service for handling complex parcel filtering logic."""

    def __init__(self, user):
        self.user = user

    def apply_filters(self, queryset: QuerySet, filter_params: dict) -> QuerySet:
        """Apply complex filtering logic to parcel queryset."""
        # Get collectivity filter based on user permissions
        collectivity_filter = UserPermission(user=self.user).get_collectivity_filter(
            communes_uuids=to_array(filter_params.get("communesUuids")),
            departments_uuids=to_array(filter_params.get("departmentsUuids")),
            regions_uuids=to_array(filter_params.get("regionsUuids")),
        )

        # Get tile set permissions
        repo = ParcelRepository(initial_queryset=queryset)
        detection_tilesets_filter = TileSetPermission(
            user=self.user,
        ).get_last_detections_filters_parcels(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            filter_tile_set_status_in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN],
            filter_collectivities=collectivity_filter,
            filter_has_collectivities=True,
        )

        # Apply repository filters
        queryset = repo.filter_(
            queryset=queryset,
            filter_collectivities=collectivity_filter,
            filter_section_contains=filter_params.get("sectionQ"),
            filter_num_parcel_contains=filter_params.get("numParcelQ"),
            filter_section=filter_params.get("section"),
            filter_num_parcel=filter_params.get("numParcel"),
            filter_detection=self._build_detection_filter(
                filter_params, detection_tilesets_filter
            ),
            filter_detections_count_gt=0,
            with_commune=True,
            with_zone_names=True,
            with_detections_count=True,
        )

        # Apply ordering
        return self._apply_ordering(queryset, filter_params.get("ordering"))

    def _build_detection_filter(
        self, filter_params: dict, additional_filter
    ) -> DetectionFilter:
        """Build complex detection filter from parameters."""
        return DetectionFilter(
            filter_score=NumberRepoFilter(
                lookup=RepoFilterLookup.GTE,
                number=float(filter_params.get("score", "0")),
            ),
            filter_object_type_uuid_in=to_array(filter_params.get("objectTypesUuids")),
            filter_custom_zone=RepoFilterCustomZone(
                interface_drawn=RepoFilterInterfaceDrawn[
                    filter_params.get(
                        "interfaceDrawn",
                        RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES.value,
                    )
                ],
                custom_zone_uuids=to_array(
                    filter_params.get("customZonesUuids"), default_value=[]
                ),
            ),
            filter_parcel_uuid_in=to_array(filter_params.get("parcelsUuids")),
            filter_detection_validation_status_in=to_enum_array(
                DetectionValidationStatus,
                filter_params.get("detectionValidationStatuses"),
            ),
            filter_detection_control_status_in=to_enum_array(
                DetectionControlStatus,
                filter_params.get("detectionControlStatuses"),
            ),
            filter_prescribed=to_bool(filter_params.get("prescripted"))
            if filter_params.get("prescripted")
            else None,
            additional_filter=additional_filter,
        )

    def _apply_ordering(self, queryset: QuerySet, ordering: Optional[str]) -> QuerySet:
        """Apply ordering logic to queryset."""
        if not ordering:
            return queryset

        if "parcel" in ordering:
            distincts = ["section", "num_parcel"]

            if ordering.startswith("-"):
                order_bys = [f"-{field}" for field in distincts]
            else:
                order_bys = distincts

        elif "detectionsCount" in ordering:
            if ordering.startswith("-"):
                order_bys = ["-detections_count"]
            else:
                order_bys = ["detections_count"]
        else:
            return queryset

        return queryset.order_by(*order_bys)
