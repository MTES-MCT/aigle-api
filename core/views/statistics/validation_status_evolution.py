from django.http import JsonResponse
from rest_framework import serializers

from core.models.tile_set import TileSet, TileSetType
from django.db.models import Count

from core.utils.data_permissions import get_user_tile_sets
from core.utils.geo import get_geometry
from core.utils.serializers import CommaSeparatedStringField, CommaSeparatedUUIDField
from rest_framework.views import APIView

from django.db.models import F

from core.views.statistics.utils import get_detections_where_clauses

from django.contrib.gis.db.models.functions import Intersection


class EndpointSerializer(serializers.Serializer):
    detectionValidationStatuses = CommaSeparatedStringField(
        required=True,
    )
    tileSetsUuids = CommaSeparatedUUIDField()

    detectionControlStatuses = CommaSeparatedStringField(required=False)
    score = serializers.FloatField(required=False)
    objectTypesUuids = CommaSeparatedUUIDField(required=False)
    customZonesUuids = CommaSeparatedUUIDField(required=False)
    prescripted = serializers.BooleanField(required=False)

    communesUuids = CommaSeparatedUUIDField(required=False)
    departmentsUuids = CommaSeparatedUUIDField(required=False)
    regionsUuids = CommaSeparatedUUIDField(required=False)


class OutputSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    date = serializers.DateTimeField()
    detectionsCount = serializers.IntegerField(source="detections_count")
    detectionValidationStatus = serializers.CharField(
        source="detection_validation_status"
    )


class StatisticsValidationStatusEvolutionView(APIView):
    def get(self, request):
        endpoint_serializer = EndpointSerializer(data=request.GET)
        endpoint_serializer.is_valid(raise_exception=True)

        tile_sets, global_geometry = get_user_tile_sets(
            user=request.user,
            filter_tile_set_type__in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            order_bys=["-date"],
        )
        tile_sets_queried = tile_sets.all()
        tile_sets_queried_uuids = [tile_set.uuid for tile_set in tile_sets_queried]

        if (
            endpoint_serializer.validated_data.get("communesUuids")
            or endpoint_serializer.validated_data.get("departmentsUuids")
            or endpoint_serializer.validated_data.get("regionsUuids")
        ):
            geozones_geometry = get_geometry(
                communes_uuids=endpoint_serializer.validated_data.get("communesUuids"),
                departments_uuids=endpoint_serializer.validated_data.get(
                    "departmentsUuids"
                ),
                regions_uuids=endpoint_serializer.validated_data.get("regionsUuids"),
            )

            if global_geometry:
                global_geometry = Intersection(global_geometry, geozones_geometry)
            else:
                global_geometry = geozones_geometry

        queryset = TileSet.objects.filter(uuid__in=tile_sets_queried_uuids)
        queryset = queryset.order_by("date")

        detections_where_clauses = get_detections_where_clauses(
            endpoint_serializer=endpoint_serializer,
            base_path_detection="detections__",
            global_geometry=global_geometry,
        )

        queryset = queryset.values(
            "uuid",
            "name",
            "date",
            detection_validation_status=F(
                "detections__detection_data__detection_validation_status"
            ),
        ).annotate(
            detections_count=Count(
                "detections",
                filter=detections_where_clauses,
            )
        )
        queryset = queryset.filter(
            detection_validation_status__in=endpoint_serializer.validated_data[
                "detectionValidationStatuses"
            ],
        )
        output_serializer = OutputSerializer(data=queryset.all(), many=True)
        output_serializer.is_valid()

        return JsonResponse(output_serializer.data, safe=False)


URL = "validation-status-evolution/"
