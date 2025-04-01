from common.views.base import BaseViewSetMixin

from django_filters import FilterSet
from django_filters import NumberFilter, ChoiceFilter
from core.models.detection import Detection

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from core.models.tile_set import TileSetType
from core.permissions.user import UserPermission
from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import DetectionRepository, RepoFilterCustomZone
from core.repository.tile_set import DEFAULT_VALUES
from core.serializers.detection import (
    DetectionListItemSerializer,
)
from core.utils.filters import ChoiceInFilter, UuidInFilter

from core.utils.pagination import CachedCountLimitOffsetPagination
from core.utils.string import to_array, to_bool, to_enum_array
from core.views.detection.utils import (
    BOOLEAN_CHOICES,
    INTERFACE_DRAWN_CHOICES,
)


class DetectionListFilter(FilterSet):
    class Meta:
        model = Detection
        fields = [
            "objectTypesUuids",
            "detectionValidationStatuses",
            "detectionControlStatuses",
            "score",
            "prescripted",
            "interfaceDrawn",
            "customZonesUuids",
            "communesUuids",
            "departmentsUuids",
            "regionsUuids",
            "tileSetsUuids",
        ]

    objectTypesUuids = UuidInFilter(method="pass_")
    detectionValidationStatuses = ChoiceInFilter(
        method="pass_",
        choices=DetectionValidationStatus.choices,
    )
    detectionControlStatuses = ChoiceInFilter(
        method="pass_",
        choices=DetectionControlStatus.choices,
    )

    score = NumberFilter(method="pass_")
    prescripted = ChoiceFilter(choices=BOOLEAN_CHOICES, method="pass_")
    interfaceDrawn = ChoiceFilter(choices=INTERFACE_DRAWN_CHOICES, method="pass_")
    customZonesUuids = UuidInFilter(method="pass_")

    communesUuids = UuidInFilter(method="pass_")
    departmentsUuids = UuidInFilter(method="pass_")
    regionsUuids = UuidInFilter(method="pass_")

    tileSetsUuids = UuidInFilter(method="pass_")

    def pass_(self, queryset, name, value):
        return queryset

    def filter_queryset(self, queryset):
        collectivity_filter = UserPermission(
            user=self.request.user
        ).get_collectivity_filter(
            communes_uuids=to_array(self.data.get("communesUuids")),
            departments_uuids=to_array(self.data.get("departmentsUuids")),
            regions_uuids=to_array(self.data.get("regionsUuids")),
        )

        repo = DetectionRepository()

        queryset = repo.list_(
            filter_score=NumberRepoFilter(
                lookup=RepoFilterLookup.GTE, number=float(self.data.get("score", "0"))
            ),
            filter_object_type_uuid_in=to_array(self.data.get("objectTypesUuids")),
            filter_custom_zone=RepoFilterCustomZone(
                interface_drawn=self.data.get("interfaceDrawn"),
                custom_zone_uuids=to_array(
                    self.data.get("customZonesUuids"), default_value=[]
                ),
            ),
            filter_tile_set_uuid_in=to_array(
                self.data.get("tileSetsUuids"), default_value=None
            ),
            filter_detection_validation_status_in=to_enum_array(
                DetectionValidationStatus,
                self.data.get("detectionValidationStatuses"),
            ),
            filter_detection_control_status_in=to_enum_array(
                DetectionControlStatus,
                self.data.get("detectionControlStatuses"),
            ),
            filter_prescribed=to_bool(self.data.get("prescripted")),
            filter_collectivities=collectivity_filter,
        )
        queryset = queryset.order_by("tile_set__date", "id")
        queryset.defer(
            "geometry",
            "tile__geometry",
            "tile_set__geometry",
            "detection_object__parcel__geometry",
            "detection_object__parcel__commune__geometry",
        )
        queryset.filter(
            detection_object__detections__tile_set__tile_set_status__in=DEFAULT_VALUES[
                "filter_tile_set_status_in"
            ],
            detection_object__detections__tile_set__tile_set_type__in=[
                TileSetType.BACKGROUND,
                TileSetType.PARTIAL,
            ],
        )
        queryset = queryset.prefetch_related(
            "detection_object",
            "detection_object__object_type",
            "detection_object__parcel",
            "detection_object__parcel__commune",
            "detection_object__detections",
            "detection_object__detections__tile_set",
            "detection_object__geo_custom_zones",
            "detection_object__geo_custom_zones__geo_custom_zone_category",
            "detection_data",
            "tile_set",
        ).select_related("detection_data")

        return queryset


class DetectionListViewSet(BaseViewSetMixin[Detection]):
    filterset_class = DetectionListFilter
    serializer_class = DetectionListItemSerializer
    queryset = Detection.objects
    pagination_class = CachedCountLimitOffsetPagination
