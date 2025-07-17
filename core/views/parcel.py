from common.views.base import BaseViewSetMixin

from django_filters import (
    FilterSet,
    CharFilter,
    NumberFilter,
    ChoiceFilter,
    OrderingFilter,
)
from django.db.models import Count

from core.models.analytic_log import AnalyticLogType
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from core.models.parcel import Parcel
from core.models.tile_set import TileSetStatus, TileSetType
from core.permissions.tile_set import TileSetPermission
from core.permissions.user import UserPermission
from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import RepoFilterCustomZone, RepoFilterInterfaceDrawn
from core.repository.parcel import DetectionFilter, ParcelRepository
from core.serializers.parcel import (
    ParcelDetailSerializer,
    ParcelListItemSerializer,
    ParcelSerializer,
    ParcelOverviewSerializer,
)
from core.utils.analytic_log import create_log
from core.utils.filters import ChoiceInFilter, UuidInFilter
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Case, When, Value, IntegerField

from django.db.models import Q, F, Sum

from core.utils.pagination import CachedCountLimitOffsetPagination
from core.utils.string import to_array, to_bool, to_enum_array
from core.views.detection.utils import BOOLEAN_CHOICES, INTERFACE_DRAWN_CHOICES


class ParcelFilter(FilterSet):
    sectionQ = CharFilter(method="pass_")
    numParcelQ = CharFilter(method="pass_")

    section = CharFilter(method="pass_")
    numParcel = CharFilter(method="pass_")

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

    ordering = OrderingFilter(fields=["parcel", "detectionsCount"], method="pass_")

    class Meta:
        model = Parcel
        fields = ["communesUuids", "sectionQ", "numParcelQ"]

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

        repo = ParcelRepository(initial_queryset=queryset)
        detection_tilesets_filter = TileSetPermission(
            user=self.request.user,
        ).get_last_detections_filters_parcels(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            filter_tile_set_status_in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN],
            filter_collectivities=collectivity_filter,
            filter_has_collectivities=True,
        )

        queryset = repo.filter_(
            queryset=queryset,
            filter_collectivities=collectivity_filter,
            filter_section_contains=self.data.get("sectionQ"),
            filter_num_parcel_contains=self.data.get("numParcelQ"),
            filter_section=self.data.get("section"),
            filter_num_parcel=self.data.get("numParcel"),
            filter_detection=DetectionFilter(
                filter_score=NumberRepoFilter(
                    lookup=RepoFilterLookup.GTE,
                    number=float(self.data.get("score", "0")),
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
                filter_parcel_uuid_in=to_array(self.data.get("parcelsUuids")),
                filter_detection_validation_status_in=to_enum_array(
                    DetectionValidationStatus,
                    self.data.get("detectionValidationStatuses"),
                ),
                filter_detection_control_status_in=to_enum_array(
                    DetectionControlStatus,
                    self.data.get("detectionControlStatuses"),
                ),
                filter_prescribed=to_bool(self.data.get("prescripted")),
                additional_filter=detection_tilesets_filter,
            ),
            filter_detections_count_gt=0,
            with_commune=True,
            with_zone_names=True,
            with_detections_count=True,
        )

        ordering = self.data.get("ordering")

        if ordering:
            if "parcel" in ordering:
                distincts = [
                    "section",
                    "num_parcel",
                ]

                if ordering.startswith("-"):
                    order_bys = [f"-{field}" for field in distincts]
                else:
                    order_bys = distincts

            if "detectionsCount" in ordering:
                if ordering.startswith("-"):
                    order_bys = ["-detections_count"]
                else:
                    order_bys = ["detections_count"]

            queryset = queryset.order_by(*order_bys)

        return queryset


class ParcelViewSet(BaseViewSetMixin[Parcel]):
    filterset_class = ParcelFilter
    queryset = Parcel.objects
    pagination_class = CachedCountLimitOffsetPagination

    def get_serializer_class(self):
        if self.action in ["retrieve", "get_download_infos"]:
            return ParcelDetailSerializer

        if self.action == "list_items":
            return ParcelListItemSerializer

        return ParcelSerializer

    def retrieve(self, request, uuid, *args, **kwargs):
        collectivity_filter = UserPermission(
            user=self.request.user
        ).get_collectivity_filter()

        repo = ParcelRepository()

        instance = repo.get(
            filter_uuid_in=[uuid],
            filter_collectivities=collectivity_filter,
            with_detections=True,
            with_commune=True,
        )
        serializer = self.get_serializer(instance)

        return Response(serializer.data)

    @action(methods=["get"], detail=True)
    def get_download_infos(self, request, uuid, *args, **kwargs):
        create_log(
            self.request.user,
            AnalyticLogType.REPORT_DOWNLOAD,
            {
                "parcelUuid": uuid,
                "detectionObjectUuid": self.request.GET.get("detectionObjectUuid"),
            },
        )

        return self.retrieve(request, uuid, *args, **kwargs)

    @action(methods=["get"], detail=False)
    def suggest_section(self, request):
        sectionQ = request.GET.get("sectionQ")

        if not sectionQ:
            return Response([])

        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)
        queryset = queryset.annotate(
            starts_with_q=Case(
                When(section__istartswith=sectionQ, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        queryset = queryset.order_by("-starts_with_q").distinct()
        queryset = queryset.values_list("section", flat=True)[:10]

        return Response(list(queryset))

    @action(methods=["get"], detail=False)
    def suggest_num_parcel(self, request):
        numParcelQ = request.GET.get("numParcelQ")

        if not numParcelQ:
            return Response([])

        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)
        queryset = queryset.annotate(
            starts_with_q=Case(
                When(num_parcel__startswith=numParcelQ, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        queryset = queryset.order_by("-starts_with_q").distinct()
        queryset = queryset.values_list("num_parcel", flat=True)[:10]

        return Response([str(num_parcel) for num_parcel in list(queryset)])

    @action(methods=["get"], detail=False)
    def list_items(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        queryset = queryset.distinct()
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)

    @action(methods=["get"], detail=False, url_path="overview")
    def get_overview(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        # Annotate each parcel with detection validation status counts
        queryset = queryset.annotate(
            total_detections=Count("detection_objects__detections__detection_data"),
            not_verified_count=Count(
                "detection_objects__detections__detection_data",
                filter=Q(
                    detection_objects__detections__detection_data__detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED
                ),
            ),
            verified_count=Count(
                "detection_objects__detections__detection_data",
                filter=Q(
                    detection_objects__detections__detection_data__detection_validation_status__in=[
                        DetectionValidationStatus.SUSPECT,
                        DetectionValidationStatus.LEGITIMATE,
                        DetectionValidationStatus.INVALIDATED,
                    ]
                ),
            ),
        )

        # Use conditional aggregation to count both categories in a single query
        result = queryset.aggregate(
            not_verified=Sum(
                Case(
                    When(not_verified_count__gt=0.5 * F("total_detections"), then=1),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            verified=Sum(
                Case(
                    When(verified_count__gte=0.5 * F("total_detections"), then=1),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            total=Count("id"),
        )

        data = {
            "not_verified": result["not_verified"] or 0,
            "verified": result["verified"] or 0,
            "total": result["total"] or 0,
        }

        serializer = ParcelOverviewSerializer(data)
        return Response(serializer.data)
