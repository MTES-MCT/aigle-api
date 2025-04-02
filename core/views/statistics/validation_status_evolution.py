from django.http import JsonResponse
from rest_framework import serializers

from django.db.models import Count

from core.models.tile_set import TileSetStatus, TileSetType
from core.permissions.tile_set import TileSetPermission
from core.permissions.user import UserPermission
from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import (
    DetectionRepository,
    RepoFilterCustomZone,
    RepoFilterInterfaceDrawn,
)
from rest_framework.views import APIView

from django.db.models import F

from core.views.statistics.utils import (
    StatisticsEndpointSerializer,
)


class OutputSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(source="tile_set_uuid")
    name = serializers.CharField(source="tile_set_name")
    date = serializers.DateTimeField(source="tile_set_date")
    detectionsCount = serializers.IntegerField(source="detections_count")
    detectionValidationStatus = serializers.CharField(
        source="detection_validation_status"
    )


class StatisticsValidationStatusEvolutionView(APIView):
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

        detection_tilesets_filter = TileSetPermission(
            user=self.request.user,
        ).get_last_detections_filters(
            filter_uuid_in=endpoint_serializer.validated_data.get("tileSetsUuids"),
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            filter_tile_set_status_in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN],
            filter_collectivities=collectivity_filter,
            filter_has_collectivities=True,
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
                interface_drawn=RepoFilterInterfaceDrawn[
                    endpoint_serializer.validated_data.get(
                        "interfaceDrawn",
                        RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES.value,
                    )
                ],
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
        queryset = queryset.filter(detection_tilesets_filter)
        queryset = queryset.values(
            tile_set_uuid=F("tile_set__uuid"),
            tile_set_name=F("tile_set__name"),
            tile_set_date=F("tile_set__date"),
            detection_validation_status=F(
                "detection_data__detection_validation_status"
            ),
        ).annotate(detections_count=Count("id", distinct=True))
        output_serializer = OutputSerializer(queryset.all(), many=True)

        return JsonResponse(output_serializer.data, safe=False)


URL = "validation-status-evolution/"
