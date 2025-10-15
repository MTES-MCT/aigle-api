from common.views.base import BaseViewSetMixin

from django_filters import FilterSet
from django_filters import NumberFilter, ChoiceFilter
from core.models.detection import Detection, DetectionSource

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from django.http import HttpResponse
from rest_framework.status import HTTP_200_OK, HTTP_202_ACCEPTED
from core.repository.detection import (
    RepoFilterInterfaceDrawn,
)
from core.serializers.detection import (
    DetectionDetailSerializer,
    DetectionInputSerializer,
    DetectionMinimalSerializer,
    DetectionMultipleInputSerializer,
    DetectionSerializer,
    DetectionUpdateSerializer,
)
from core.utils.filters import ChoiceInFilter, UuidInFilter
from rest_framework.decorators import action

from core.views.detection.utils import (
    BOOLEAN_CHOICES,
    filter_prescripted,
    filter_score,
)


class DetectionGeoFilter(FilterSet):
    objectTypesUuids = UuidInFilter(method="pass_")
    customZonesUuids = UuidInFilter(method="pass_")
    tileSetsUuids = UuidInFilter(method="pass_")
    detectionValidationStatuses = ChoiceInFilter(
        field_name="detection_data__detection_validation_status",
        choices=DetectionValidationStatus.choices,
    )
    detectionControlStatuses = ChoiceInFilter(
        field_name="detection_data__detection_control_status",
        choices=DetectionControlStatus.choices,
    )
    detectionPrescriptionStatuses = ChoiceInFilter(
        field_name="detection_data__detection_prescription_status",
        choices=DetectionControlStatus.choices,
    )

    neLat = NumberFilter(method="pass_")
    neLng = NumberFilter(method="pass_")

    swLat = NumberFilter(method="pass_")
    swLng = NumberFilter(method="pass_")

    score = NumberFilter(method="filter_score")
    prescripted = ChoiceFilter(choices=BOOLEAN_CHOICES, method="filter_prescripted")
    interfaceDrawn = ChoiceFilter(
        choices=[(choice.value, choice.name) for choice in RepoFilterInterfaceDrawn],
        method="pass_",
    )

    def pass_(self, queryset, name, value):  # noqa: ARG002
        return queryset

    class Meta:
        model = Detection
        fields = ["neLat", "neLng", "swLat", "swLng", "tileSetsUuids"]
        geo_field = "geometry"

    def filter_score(self, queryset, name, value):
        return filter_score(queryset, name, value)

    def filter_prescripted(self, queryset, name, value):
        return filter_prescripted(queryset, name, value)

    def filter_queryset(self, queryset):
        from core.services.detection_geo_filter import DetectionGeoFilterService

        queryset = super().filter_queryset(queryset)

        filter_service = DetectionGeoFilterService(user=self.request.user)
        return filter_service.apply_filters(queryset, self.data)


class DetectionGeoViewSet(BaseViewSetMixin[Detection]):
    filterset_class = DetectionGeoFilter

    @action(methods=["post"], detail=False, url_path="multiple")
    def edit_multiple(self, request):
        serializer = DetectionMultipleInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        detections_queryset = self.get_queryset()
        detections_queryset = detections_queryset.filter(
            uuid__in=serializer.validated_data["uuids"]
        )
        detections = detections_queryset.all()

        # Use bulk update service for business logic
        from core.services.detection_bulk_update import DetectionBulkUpdateService

        bulk_update_service = DetectionBulkUpdateService(user=request.user)
        bulk_update_service.update_multiple_detections(
            detections=detections,
            update_data=serializer.validated_data,
        )

        return HttpResponse(status=HTTP_200_OK)

    def get_serializer_class(self):
        if self.action in ["create"]:
            return DetectionInputSerializer

        if self.action in ["partial_update", "update"]:
            return DetectionUpdateSerializer

        detail = bool(self.request.query_params.get("detail"))
        geo_feature = bool(self.request.query_params.get("geoFeature"))

        if self.action in ["list"] and geo_feature:
            return DetectionMinimalSerializer

        if detail:
            return DetectionDetailSerializer

        return DetectionSerializer

    def get_queryset(self):
        queryset = Detection.objects.order_by("tile_set__date", "id")
        queryset = queryset.prefetch_related(
            "detection_object", "detection_object__object_type", "tile", "tile_set"
        ).select_related("detection_data")
        return queryset

    @action(methods=["patch"], detail=True, url_path="force-visible")
    def force_visible(self, request, uuid):  # noqa: ARG002
        queryset = self.get_queryset()
        queryset = queryset.filter(uuid=uuid)
        detection = queryset.first()

        detection.detection_source = DetectionSource.INTERFACE_FORCED_VISIBLE
        detection.save()

        return HttpResponse(status=HTTP_202_ACCEPTED)
