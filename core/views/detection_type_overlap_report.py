from django.db.models import F, FloatField, OuterRef, Prefetch, Subquery, Value
from django.db.models.functions import Cast, Greatest
from django_filters import CharFilter, FilterSet, OrderingFilter, UUIDFilter
from rest_framework.viewsets import ReadOnlyModelViewSet

from core.models.detection_type_overlap_report import (
    DetectionTypeOverlapReport,
    DetectionTypeOverlapReportObjectType,
)
from core.models.tile_set import TileSet
from core.serializers.detection_type_overlap_report import (
    DetectionTypeOverlapReportSerializer,
)
from core.utils.permissions import SuperAdminRolePermission
from core.utils.string import normalize


def overlap_rate(count_field: str):
    # 0 detections gives 0 rather than NULL, which a descending sort would put first
    return Cast(count_field, FloatField()) / Greatest(F("detections_count"), Value(1))


class StableOrderingFilter(OrderingFilter):
    def filter(self, qs, value):
        qs = super().filter(qs, value)
        # equal values (many 0 % rates) must not swap rows between pages
        return qs.order_by(*qs.query.order_by, "id") if value else qs


class DetectionTypeOverlapReportFilter(FilterSet):
    q = CharFilter(method="search")
    geoZoneUuid = UUIDFilter(field_name="geo_zone__uuid")
    ordering = StableOrderingFilter(
        fields=(
            ("geo_zone__name_normalized", "geoZoneName"),
            ("year", "year"),
            ("report_date", "reportDate"),
            ("detections_count", "detectionsCount"),
            ("overlapping_rate", "overlappingRate"),
            ("overlapping_prescribable_rate", "overlappingPrescribableRate"),
        )
    )

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
            .annotate(
                overlapping_rate=overlap_rate("overlapping_count"),
                overlapping_prescribable_rate=overlap_rate(
                    "overlapping_prescribable_count"
                ),
                # a subquery, not Max(): an aggregate would GROUP BY every column
                year=Subquery(
                    TileSet.objects.filter(
                        detection_type_overlap_reports=OuterRef("pk")
                    )
                    .order_by("-date")
                    .values("date")[:1]
                ),
            )
            .order_by("-report_date", "id")
        )
