from common.views.base import BaseViewSetMixin

from django_filters import FilterSet
from django_filters import NumberFilter, ChoiceFilter
from core.models.detection import Detection
from django.http import JsonResponse
from django.db.models import Prefetch
from django.http import HttpResponse
import csv

from django.db.models import F
from django.db.models import Count
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from core.models.tile_set import TileSet, TileSetStatus, TileSetType
from core.permissions.tile_set import TileSetPermission
from core.permissions.user import UserPermission
from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import (
    DetectionRepository,
    RepoFilterCustomZone,
    RepoFilterInterfaceDrawn,
)
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
from rest_framework.decorators import action
from rest_framework import serializers
from rest_framework.response import Response
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models.functions import Coalesce


class DetectionListOverviewValidationStatusItemSerializer(serializers.Serializer):
    detectionValidationStatus = serializers.CharField(
        source="detection_validation_status"
    )
    count = serializers.IntegerField()


class DetectionListOverviewSerializer(serializers.Serializer):
    validationStatusesCount = DetectionListOverviewValidationStatusItemSerializer(
        many=True,
    )
    totalCount = serializers.IntegerField()


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

        detection_tilesets_filter = TileSetPermission(
            user=self.request.user,
        ).get_last_detections_filters(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            filter_tile_set_status_in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN],
            filter_collectivities=collectivity_filter,
            filter_has_collectivities=True,
        )

        if not detection_tilesets_filter:
            return []

        repo = DetectionRepository()

        queryset = repo.filter_(
            queryset=queryset,
            filter_score=NumberRepoFilter(
                lookup=RepoFilterLookup.GTE, number=float(self.data.get("score", "0"))
            ),
            filter_object_type_uuid_in=to_array(self.data.get("objectTypesUuids")),
            filter_custom_zone=RepoFilterCustomZone(
                interface_drawn=RepoFilterInterfaceDrawn[
                    self.data.get(
                        "interfaceDrawn",
                        RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES.value,
                    )
                ],
                custom_zone_uuids=to_array(
                    self.data.get("customZonesUuids"), default_value=[]
                ),
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
        queryset = queryset.order_by("id")
        queryset = queryset.filter(detection_tilesets_filter)
        queryset = queryset.filter(detection_object__tile_sets__id__in=[17, 25, 27, 28])
        queryset = queryset.defer(
            "geometry",
            "tile__geometry",
            "detection_object__parcel__geometry",
            "detection_object__parcel__commune__geometry",
        )
        queryset = queryset.prefetch_related(
            "detection_object",
            "detection_object__object_type",
            "detection_object__parcel",
            "detection_object__parcel__commune",
            "detection_object__detections",
            Prefetch(
                "detection_object__tile_sets",
                queryset=TileSet.objects.filter(
                    tile_set_status__in=DEFAULT_VALUES["filter_tile_set_status_in"],
                    tile_set_type__in=[
                        TileSetType.BACKGROUND,
                        TileSetType.PARTIAL,
                    ],
                )
                .order_by(*DEFAULT_VALUES["order_bys"])
                .distinct(),
            ),
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

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        queryset = queryset.distinct("id")

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)

    @action(methods=["get"], detail=False, url_path="download-csv")
    def download_csv(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        response = HttpResponse(
            content_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="somefilename.csv"'},
        )
        queryset = queryset.values_list(
            "detection_object__id",
            "detection_object__address",
            "detection_object__object_type__name",
            "detection_object__parcel__section",
            "detection_object__parcel__num_parcel",
            "score",
            "detection_source",
            "detection_data__detection_control_status",
            "detection_data__detection_prescription_status",
            "detection_data__detection_validation_status",
        ).annotate(
            tile_sets=ArrayAgg("detection_object__tile_sets__name", distinct=True),
            custom_zones=ArrayAgg(
                Coalesce(
                    "detection_object__geo_custom_zones__geo_custom_zone_category__name",
                    "detection_object__geo_custom_zones__name",
                ),
                distinct=True,
            ),
        )

        results = combine_duplicate_rows(list(queryset))

        writer = csv.writer(response)
        writer.writerow(
            [
                "Object n°",
                "Adresse",
                "Type",
                "Parcelle (section)",
                "Parcelle (numéro)",
                "Score",
                "Source",
                "Statut de contrôle",
                "Prescription",
                "Statut de validation",
                "Millésimes",
                "Zones à enjeux",
            ]
        )
        writer.writerows(results)

        return response

    @action(methods=["get"], detail=False, url_path="overview")
    def get_overview(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        queryset = (
            queryset.values(
                detection_validation_status=F(
                    "detection_data__detection_validation_status"
                ),
            )
            .annotate(
                count=Count("id", distinct=True),
            )
            .order_by("detection_validation_status")
        )

        statuses_count_raw = queryset.all()
        overview = DetectionListOverviewSerializer(
            data={
                "validationStatusesCount": [
                    DetectionListOverviewValidationStatusItemSerializer(
                        statuses_count
                    ).data
                    for statuses_count in statuses_count_raw
                ],
                "totalCount": sum(
                    [status_count["count"] for status_count in statuses_count_raw]
                ),
            }
        )

        return JsonResponse(overview.initial_data)


# utils


def combine_duplicate_rows(results):
    combined_data = {}

    # Pre-define indices for direct access - faster than repeated indexing
    ID_INDEX = 0
    TILE_SETS_INDEX = 10
    CUSTOM_ZONES_INDEX = 11

    for row in results:
        obj_id = row[ID_INDEX]

        if obj_id not in combined_data:
            # Use the entire tuple directly - avoiding dict creation for base data
            combined_data[obj_id] = [
                row,
                set(row[TILE_SETS_INDEX]),
                set(row[CUSTOM_ZONES_INDEX]),
            ]
        else:
            # Only update the sets, which is what varies between duplicates
            combined_data[obj_id][1].update(row[TILE_SETS_INDEX])
            combined_data[obj_id][2].update(row[CUSTOM_ZONES_INDEX])

    # Convert to final format
    final_results = []
    for base_data, tile_sets, custom_zones in combined_data.values():
        # Create dictionary only once per unique ID
        result = [
            *base_data[:TILE_SETS_INDEX],
            ", ".join(tile_sets),
            ", ".join(custom_zones),
        ]
        final_results.append(result)

    return final_results
