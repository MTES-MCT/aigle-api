from common.views.base import BaseViewSetMixin

from django_filters import FilterSet, CharFilter

from core.models.analytic_log import AnalyticLogType
from core.models.parcel import Parcel
from core.serializers.parcel import ParcelDetailSerializer, ParcelSerializer
from core.utils.analytic_log import create_log
from core.utils.filters import UuidInFilter
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Case, When, Value, IntegerField


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

    def get_serializer_context(self):
        context = {"request": self.request}

        if self.request.GET.get("tileSetUuid"):
            context["tile_set_uuid"] = self.request.GET.get("tileSetUuid")

        return context

    def get_queryset(self):
        queryset = Parcel.objects.order_by("id")
        queryset = queryset.prefetch_related("commune")

        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                "detection_objects",
                "detection_objects__detections",
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

        return Response(list(queryset))
