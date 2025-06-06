from collections import defaultdict
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

from core.utils.serializers import CommaSeparatedUUIDField
from core.views.statistics.utils import (
    StatisticsEndpointSerializer,
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
        collectivity_filter = UserPermission(user=request.user).get_collectivity_filter(
            communes_uuids=endpoint_serializer.validated_data.get("communesUuids"),
            departments_uuids=endpoint_serializer.validated_data.get(
                "departmentsUuids"
            ),
            regions_uuids=endpoint_serializer.validated_data.get("regionsUuids"),
        )

        other_object_types_uuids = endpoint_serializer.validated_data.get(
            "otherObjectTypesUuids", []
        )
        all_object_types_uuids = (
            endpoint_serializer.validated_data.get("objectTypesUuids", [])
            + other_object_types_uuids
        )

        tile_sets = TileSetPermission(
            user=self.request.user,
        ).list_(
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
            filter_object_type_uuid_in=all_object_types_uuids or None,
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
            filter_tile_set_uuid_in=[tile_set.uuid for tile_set in tile_sets],
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
                "detection_data__detection_validation_status",
            ),
            object_type_uuid=F("detection_object__object_type__uuid"),
            object_type_name=F("detection_object__object_type__name"),
            object_type_color=F("detection_object__object_type__color"),
        ).annotate(detections_count=Count("id", distinct=True))

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
