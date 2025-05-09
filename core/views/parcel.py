from common.views.base import BaseViewSetMixin

from django_filters import FilterSet, CharFilter
from django.db.models import Prefetch

from core.models.analytic_log import AnalyticLogType
from core.models.detection import Detection, DetectionSource
from core.models.detection_data import (
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.models.detection_object import DetectionObject
from core.models.parcel import Parcel
from core.repository.tile_set import DEFAULT_VALUES
from core.serializers.parcel import ParcelDetailSerializer, ParcelSerializer
from core.utils.analytic_log import create_log
from core.utils.filters import UuidInFilter
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Case, When, Value, IntegerField

from django.db.models import Q


class ParcelFilter(FilterSet):
    communeUuids = UuidInFilter(method="search_commune_uuids")
    sectionQ = CharFilter(method="search_section")
    numParcelQ = CharFilter(method="search_num_parcel")

    section = CharFilter(field_name="section")
    numParcel = CharFilter(field_name="num_parcel")

    class Meta:
        model = Parcel
        fields = ["communeUuids", "sectionQ", "numParcelQ"]

    def search_commune_uuids(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(commune__uuid__in=value)

    def search_section(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(section__icontains=value)

    def search_num_parcel(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(num_parcel__icontains=value)


class ParcelViewSet(BaseViewSetMixin[Parcel]):
    filterset_class = ParcelFilter

    def get_serializer_class(self):
        if self.action == "retrieve" or self.action == "get_download_infos":
            return ParcelDetailSerializer

        return ParcelSerializer

    def get_queryset(self):
        queryset = Parcel.objects.order_by("id")
        queryset = queryset.prefetch_related("commune")

        if self.action in ["retrieve", "get_download_infos"]:
            queryset = queryset.prefetch_related(
                Prefetch(
                    "detection_objects",
                    queryset=DetectionObject.objects.select_related(
                        "object_type",
                    )
                    .prefetch_related(
                        "geo_custom_zones", "geo_custom_zones__geo_custom_zone_category"
                    )
                    .filter(
                        ~Q(
                            detections__detection_data__detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED
                        )
                        & Q(
                            Q(
                                detections__detection_source__in=[
                                    DetectionSource.INTERFACE_DRAWN,
                                    DetectionSource.INTERFACE_FORCED_VISIBLE,
                                ]
                            )
                            | Q(
                                Q(
                                    detections__detection_data__detection_validation_status__in=[
                                        DetectionValidationStatus.DETECTED_NOT_VERIFIED,
                                        DetectionValidationStatus.SUSPECT,
                                    ]
                                )
                                & Q(detections__score__gte=0.3)
                            )
                            | Q(
                                Q(
                                    detections__detection_data__detection_validation_status__in=[
                                        DetectionValidationStatus.SUSPECT,
                                    ]
                                )
                                & Q(detections__score__lt=0.3)
                            )
                        )
                        & Q(
                            detections__tile_set__tile_set_status__in=DEFAULT_VALUES[
                                "filter_tile_set_status_in"
                            ]
                        )
                    ),
                ),
                Prefetch(
                    "detection_objects__detections",
                    queryset=Detection.objects.select_related(
                        "tile",
                        "tile_set",
                        "detection_data",
                        "detection_data__user_last_update",
                    ).filter(
                        ~Q(
                            detection_data__detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED
                        )
                        & Q(
                            Q(
                                detection_source__in=[
                                    DetectionSource.INTERFACE_DRAWN,
                                    DetectionSource.INTERFACE_FORCED_VISIBLE,
                                ]
                            )
                            | Q(
                                detection_data__detection_validation_status__in=[
                                    DetectionValidationStatus.DETECTED_NOT_VERIFIED,
                                    DetectionValidationStatus.SUSPECT,
                                ]
                            )
                        )
                        & Q(
                            tile_set__tile_set_status__in=DEFAULT_VALUES[
                                "filter_tile_set_status_in"
                            ]
                        )
                    ),
                ),
            )

        return queryset

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
        q = request.GET.get("q")

        if not q:
            return Response([])

        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)
        queryset = queryset.filter(section__icontains=q)
        queryset = queryset.annotate(
            starts_with_q=Case(
                When(section__istartswith=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        queryset = queryset.order_by("-starts_with_q").distinct()
        queryset = queryset.values_list("section", flat=True)[:10]

        return Response(list(queryset))

    @action(methods=["get"], detail=False)
    def suggest_num_parcel(self, request):
        q = request.GET.get("q")

        if not q:
            return Response([])

        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)
        queryset = queryset.filter(num_parcel__icontains=q)
        queryset = queryset.annotate(
            starts_with_q=Case(
                When(num_parcel__startswith=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        queryset = queryset.order_by("-starts_with_q").distinct()
        queryset = queryset.values_list("num_parcel", flat=True)[:10]

        return Response([str(num_parcel) for num_parcel in list(queryset)])
