from common.views.base import BaseViewSetMixin

from operator import or_
from django.db.models import Q
from functools import reduce
from django_filters import FilterSet
from django_filters import NumberFilter, ChoiceFilter
from core.models.detection import Detection, DetectionSource
from django.core.exceptions import BadRequest

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from rest_framework.status import HTTP_200_OK
from django.http import HttpResponse
from core.models.detection_object import DetectionObject
from core.models.object_type import ObjectType
from core.models.tile_set import TileSetType
from core.models.user_group import UserGroupRight
from core.serializers.detection import (
    DetectionDetailSerializer,
    DetectionInputSerializer,
    DetectionMinimalSerializer,
    DetectionMultipleInputSerializer,
    DetectionSerializer,
    DetectionUpdateSerializer,
)
from core.utils.data_permissions import (
    get_user_group_rights,
    get_user_object_types_with_status,
    get_user_tile_sets,
)
from simple_history.utils import bulk_update_with_history
from core.utils.filters import ChoiceInFilter, UuidInFilter
from django.contrib.gis.geos import Polygon
from rest_framework.decorators import action
from django.contrib.gis.db.models.functions import Intersection

from core.utils.geo import get_geometry
from core.views.detection.utils import (
    BOOLEAN_CHOICES,
    INTERFACE_DRAWN_CHOICES,
    filter_custom_zones_uuids,
    filter_prescripted,
    filter_score,
)


class DetectionListFilter(FilterSet):
    class Meta:
        model = Detection
        fields = ["tileSetsUuids"]
        geo_field = "geometry"

    objectTypesUuids = UuidInFilter(method="filter_object_types_uuids")
    detectionValidationStatuses = ChoiceInFilter(
        field_name="detection_data__detection_validation_status",
        choices=DetectionValidationStatus.choices,
    )
    detectionControlStatuses = ChoiceInFilter(
        field_name="detection_data__detection_control_status",
        choices=DetectionControlStatus.choices,
    )

    score = NumberFilter(method="filter_score")
    prescripted = ChoiceFilter(choices=BOOLEAN_CHOICES, method="filter_prescripted")
    interfaceDrawn = ChoiceFilter(choices=INTERFACE_DRAWN_CHOICES, method="pass_")
    customZonesUuids = UuidInFilter(method="filter_custom_zones_uuids")

    communesUuids = UuidInFilter(method="pass_")
    departmentsUuids = UuidInFilter(method="pass_")
    regionsUuids = UuidInFilter(method="pass_")

    def pass_(self, queryset, name, value):
        return queryset

    def filter_object_types_uuids(self, queryset, name, value):
        if not value:
            return queryset

        object_types_uuids = value.split(",")

        return queryset.filter(
            detection_object__object_type__uuid__in=object_types_uuids
        )

    def filter_score(self, queryset, name, value):
        return filter_score(queryset, name, value)

    def filter_prescripted(self, queryset, name, value):
        return filter_prescripted(queryset, name, value)

    def filter_queryset(self, queryset):
        queryset = filter_custom_zones_uuids(data=self.data, queryset=queryset)

        # filter geo collectivities

        communes_uuids = (
            self.data.get("communesUuids").split(",")
            if self.data.get("communesUuids")
            else []
        )
        departments_uuids = (
            self.data.get("departmentsUuids").split(",")
            if self.data.get("departmentsUuids")
            else []
        )
        regions_uuids = (
            self.data.get("regionsUuids").split(",")
            if self.data.get("regionsUuids")
            else []
        )

        return queryset


class DetectionListViewSet(BaseViewSetMixin[Detection]):
    filterset_class = DetectionListFilter
    serializer_class = DetectionDetailSerializer

    def get_queryset(self):
        queryset = Detection.objects.order_by("tile_set__date", "id")
        queryset = queryset.prefetch_related(
            "detection_object", "detection_object__object_type", "tile", "tile_set"
        ).select_related("detection_data")
        return queryset
