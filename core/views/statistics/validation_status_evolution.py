from django.http import JsonResponse
from rest_framework import serializers

from core.models.detection import Detection
from django.db.models import Count

from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import DetectionRepository, RepoFilterCustomZone
from core.utils.serializers import CommaSeparatedStringField, CommaSeparatedUUIDField
from rest_framework.views import APIView

from django.db.models import F


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
    uuid = serializers.UUIDField(source="tile_set_uuid")
    name = serializers.CharField(source="tile_set_name")
    date = serializers.DateTimeField(source="tile_set_date")
    detectionsCount = serializers.IntegerField(source="detections_count")
    detectionValidationStatus = serializers.CharField(
        source="detection_validation_status"
    )


class StatisticsValidationStatusEvolutionView(APIView):
    def get(self, request):
        endpoint_serializer = EndpointSerializer(data=request.GET)
        endpoint_serializer.is_valid(raise_exception=True)

        communes_uuids = endpoint_serializer.validated_data.get("communesUuids") or []
        departments_uuids = (
            endpoint_serializer.validated_data.get("departmentsUuids") or []
        )
        regions_uuids = endpoint_serializer.validated_data.get("regionsUuids") or []

        collectivities_uuids = communes_uuids + departments_uuids + regions_uuids

        repo = DetectionRepository(queryset=Detection.objects)

        queryset, _ = repo._filter(
            filter_collectivity_uuid_in=collectivities_uuids or None,
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
            tile_set_uuid=F("tile_set__uuid"),
            tile_set_name=F("tile_set__name"),
            tile_set_date=F("tile_set__date"),
            detection_validation_status=F(
                "detection_data__detection_validation_status"
            ),
        ).annotate(detections_count=Count("id"))
        output_serializer = OutputSerializer(data=queryset.all(), many=True)
        output_serializer.is_valid()

        return JsonResponse(output_serializer.data, safe=False)


URL = "validation-status-evolution/"
