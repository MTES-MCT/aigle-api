from django.http import JsonResponse
from rest_framework import serializers

from django.db.models import Count

from core.permissions.user import UserPermission
from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import DetectionRepository, RepoFilterCustomZone
from rest_framework.views import APIView

from django.db.models import F

from core.views.statistics.utils import (
    StatisticsEndpointSerializer,
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

        repo = DetectionRepository()

        collectivity_filter = UserPermission(user=request.user).get_collectivity_filter(
            communes_uuids=endpoint_serializer.validated_data.get("communesUuids"),
            departments_uuids=endpoint_serializer.validated_data.get(
                "departmentsUuids"
            ),
            regions_uuids=endpoint_serializer.validated_data.get("regionsUuids"),
        )

        queryset = repo.filter_(
            queryset=repo.initial_queryset,
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
            filter_collectivities=collectivity_filter,
        )

        queryset = queryset.values(
            detection_validation_status=F(
                "detection_data__detection_validation_status"
            ),
        ).annotate(detections_count=Count("id"))
        output_serializer = OutputSerializer(queryset.all(), many=True)

        return JsonResponse(output_serializer.data, safe=False)


URL = "validation-status-evolution/"
