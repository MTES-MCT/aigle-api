from common.views.base import BaseViewSetMixin

from django_filters import FilterSet
from django_filters import NumberFilter, ChoiceFilter
from core.models.detection import Detection

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import DetectionRepository, RepoFilterCustomZone
from core.serializers.detection import (
    DetectionDetailSerializer,
)
from core.utils.filters import ChoiceInFilter, UuidInFilter

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
        # filter geo collectivities

        communes_uuids = to_array(self.data.get("communesUuids"), default_value=[])
        departments_uuids = to_array(
            self.data.get("departmentsUuids"), default_value=[]
        )
        regions_uuids = to_array(self.data.get("regionsUuids"), default_value=[])

        collectivities_uuids = communes_uuids + departments_uuids + regions_uuids

        repo = DetectionRepository(queryset=queryset)

        queryset = repo._filter(
            filter_collectivity_uuid_in=collectivities_uuids or None,
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
        )

        return queryset


class DetectionListViewSet(BaseViewSetMixin[Detection]):
    filterset_class = DetectionListFilter
    serializer_class = DetectionDetailSerializer

    def get_queryset(self):
        queryset = Detection.objects.order_by("tile_set__date", "id")
        queryset = queryset.prefetch_related(
            "detection_object",
            "detection_object__object_type",
            "detection_object__parcel",
            "tile",
            "tile_set",
        ).select_related("detection_data")
        return queryset
