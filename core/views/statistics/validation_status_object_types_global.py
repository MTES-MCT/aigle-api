from collections import defaultdict
from django.http import JsonResponse
from rest_framework import serializers

from django.db.models import Count

from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.detection import DetectionRepository, RepoFilterCustomZone
from rest_framework.views import APIView

from django.db.models import F

from core.utils.serializers import CommaSeparatedUUIDField
from core.views.statistics.utils import (
    StatisticsEndpointSerializer,
    get_collectivities_uuids,
)


class StatisticsValidationStatusObjectTypesGlobal(StatisticsEndpointSerializer):
    otherObjectTypesUuids = CommaSeparatedUUIDField(required=False)


class OutputSerializer(serializers.Serializer):
    detectionsCount = serializers.IntegerField(source="detections_count")
    detectionValidationStatus = serializers.CharField(
        source="detection_validation_status"
    )
    objectTypeUuid = serializers.CharField(source="object_type_uuid")
    objectTypeName = serializers.CharField(source="object_type_name")
    objectTypeColor = serializers.CharField(source="object_type_color")


class StatisticsValidationStatusObjectTypesGlobalView(APIView):
    def get(self, request):
        endpoint_serializer = StatisticsValidationStatusObjectTypesGlobal(
            data=request.GET
        )
        endpoint_serializer.is_valid(raise_exception=True)

        repo = DetectionRepository()
        collectivities_uuids = get_collectivities_uuids(
            endpoint_serializer=endpoint_serializer
        )

        other_object_types_uuids = endpoint_serializer.validated_data.get(
            "otherObjectTypesUuids", []
        )
        all_object_types_uuids = (
            endpoint_serializer.validated_data.get("objectTypesUuids", [])
            + other_object_types_uuids
        )

        queryset, _ = repo._filter(
            filter_collectivity_uuid_in=collectivities_uuids,
            filter_score=NumberRepoFilter(
                lookup=RepoFilterLookup.GTE,
                number=float(endpoint_serializer.validated_data.get("score", "0")),
            ),
            filter_object_type_uuid_in=all_object_types_uuids or None,
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
                "detection_data__detection_validation_status",
            ),
            object_type_uuid=F("detection_object__object_type__uuid"),
            object_type_name=F("detection_object__object_type__name"),
            object_type_color=F("detection_object__object_type__color"),
        ).annotate(detections_count=Count("id"))

        if other_object_types_uuids:
            data_others_map = defaultdict(int)
            data = []

            for item in queryset.all():
                if str(item["object_type_uuid"]) not in other_object_types_uuids:
                    data.append(item)
                    continue

                data_others_map[item["detection_validation_status"]] += item[
                    "detections_count"
                ]

            for detection_validation_status, detections_count in dict(
                data_others_map
            ).items():
                data.append(
                    {
                        "detection_validation_status": detection_validation_status,
                        "object_type_uuid": "OTHER_OBJECT_TYPES",
                        "object_type_name": "Autres",
                        "object_type_color": "#FFFFFF",
                        "detections_count": detections_count,
                    }
                )
        else:
            data = queryset.all()

        output_serializer = OutputSerializer(data, many=True)

        return JsonResponse(output_serializer.data, safe=False)


URL = "validation-status-evolution/"
