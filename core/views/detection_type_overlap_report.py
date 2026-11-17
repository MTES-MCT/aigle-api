from django.db.models import Prefetch
from django_filters import CharFilter, FilterSet, UUIDFilter
from rest_framework.viewsets import ReadOnlyModelViewSet

from core.models.detection_type_overlap_report import (
    DetectionTypeOverlapReport,
    DetectionTypeOverlapReportObjectType,
)
from core.serializers.detection_type_overlap_report import (
    DetectionTypeOverlapReportSerializer,
)
from core.utils.permissions import SuperAdminRolePermission
from core.utils.string import normalize


class DetectionTypeOverlapReportFilter(FilterSet):
    q = CharFilter(method="search")
    geoZoneUuid = UUIDFilter(field_name="geo_zone__uuid")

    class Meta:
        model = DetectionTypeOverlapReport
        fields = ["q", "geoZoneUuid"]

    def search(self, queryset, name, value):
        return queryset.filter(geo_zone__name_normalized__icontains=normalize(value))


class DetectionTypeOverlapReportViewSet(ReadOnlyModelViewSet):
    lookup_field = "uuid"
    filterset_class = DetectionTypeOverlapReportFilter
    permission_classes = [SuperAdminRolePermission]
    serializer_class = DetectionTypeOverlapReportSerializer

    def get_serializer_context(self):
        return {"request": self.request}

    def get_queryset(self):
        return (
            DetectionTypeOverlapReport.objects.select_related("geo_zone")
            # a department outline weighs tens of kB
            .defer("geo_zone__geometry")
            .prefetch_related(
                "tile_sets",
                Prefetch(
                    "object_types",
                    queryset=DetectionTypeOverlapReportObjectType.objects.select_related(
                        "object_type"
                    ).order_by("object_type__name"),
                ),
            )
            .order_by("-report_date")
        )
