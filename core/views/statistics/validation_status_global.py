from django.http import JsonResponse
from rest_framework import serializers

from core.models.detection import Detection
from django.db.models import Count

from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import DetectionRepository, RepoFilterCustomZone
from rest_framework.views import APIView

from django.db.models import F

from core.views.statistics.utils import (
    StatisticsEndpointSerializer,
    get_collectivities_uuids,
)


class OutputSerializer(serializers.Serializer):
    detectionsCount = serializers.IntegerField(source="detections_count")
    detectionValidationStatus = serializers.CharField(
        source="detection_validation_status"
    )


class StatisticsValidationStatusGlobalView(APIView):
    def get(self, request):
        endpoint_serializer = StatisticsEndpointSerializer(data=request.GET)
        endpoint_serializer.is_valid(raise_exception=True)

        repo = DetectionRepository(queryset=Detection.objects)
        collectivities_uuids = get_collectivities_uuids(
            endpoint_serializer=endpoint_serializer
        )

        queryset, _ = repo._filter(
            filter_collectivity_uuid_in=collectivities_uuids,
            filter_score=NumberRepoFilter(
                lookup=RepoFilterLookup.GTE,
                number=float(endpoint_serializer.validated_data.get("score", "0")),
            ),
            filter_object_type_uuid_in=endpoint_serializer.validated_data.get(
                "objectTypesUuids"
            ),
            filter_custom_zone=RepoFilterCustomZone(
                interface_drawn=endpoint_serializer.validated_data.get(
                    "interfaceDrawn"
                ),
                custom_zone_uuids=endpoint_serializer.validated_data.get(
                    "customZonesUuids"
                )
                or [],
            ),
            filter_tile_set_uuid_in=endpoint_serializer.validated_data.get(
                "tileSetsUuids"
            ),
            filter_detection_validation_status_in=endpoint_serializer.validated_data.get(
                "detectionValidationStatuses"
            ),
            filter_detection_control_status_in=endpoint_serializer.validated_data.get(
                "detectionControlStatuses"
            ),
            filter_prescribed=endpoint_serializer.validated_data.get("prescripted"),
        )

        queryset = queryset.values(
            detection_validation_status=F(
                "detection_data__detection_validation_status"
            ),
        ).annotate(detections_count=Count("id"))
        output_serializer = OutputSerializer(data=queryset.all(), many=True)
        output_serializer.is_valid()

        return JsonResponse(output_serializer.data, safe=False)


URL = "validation-status-evolution/"
