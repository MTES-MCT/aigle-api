from common.views.base import BaseViewSetMixin

from django_filters import (
    FilterSet,
    CharFilter,
    NumberFilter,
    ChoiceFilter,
    OrderingFilter,
)

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from core.models.parcel import Parcel
from core.serializers.parcel import (
    ParcelDetailSerializer,
    ParcelListItemSerializer,
    ParcelSerializer,
    ParcelOverviewSerializer,
)
from core.utils.filters import ChoiceInFilter, UuidInFilter
from rest_framework.response import Response
from rest_framework.decorators import action


from core.utils.pagination import CachedCountLimitOffsetPagination
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

    def pass_(self, queryset, name, value):  # noqa: ARG002
        return queryset

    def filter_queryset(self, queryset):
        from core.services.parcel_filter import ParcelFilterService

        filter_service = ParcelFilterService(user=self.request.user)
        return filter_service.apply_filters(queryset, self.data)


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

    def retrieve(self, request, uuid):
        from core.services.parcel import ParcelService

        instance = ParcelService.get_parcel_detail(uuid=uuid, user=request.user)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(methods=["get"], detail=True)
    def get_download_infos(self, request, uuid):
        from core.services.parcel import ParcelService

        ParcelService.log_parcel_download(
            user=request.user,
            parcel_uuid=uuid,
            detection_object_uuid=request.GET.get("detectionObjectUuid"),
        )
        return self.retrieve(request, uuid)

    @action(methods=["get"], detail=False)
    def suggest_section(self, request):
        from core.services.parcel import ParcelService

        section_query = request.GET.get("sectionQ")
        if not section_query:
            return Response([])

        queryset = self.filter_queryset(self.get_queryset())
        suggestions = ParcelService.get_section_suggestions(
            queryset=queryset, section_query=section_query
        )
        return Response(suggestions)

    @action(methods=["get"], detail=False)
    def suggest_num_parcel(self, request):
        from core.services.parcel import ParcelService

        num_parcel_query = request.GET.get("numParcelQ")
        if not num_parcel_query:
            return Response([])

        queryset = self.filter_queryset(self.get_queryset())
        suggestions = ParcelService.get_num_parcel_suggestions(
            queryset=queryset, num_parcel_query=num_parcel_query
        )
        return Response(suggestions)

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
        from core.services.parcel import ParcelService

        queryset = self.filter_queryset(self.get_queryset())
        data = ParcelService.get_parcel_overview_statistics(queryset=queryset)
        serializer = ParcelOverviewSerializer(data)
        return Response(serializer.data)
