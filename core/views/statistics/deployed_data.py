from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services.deployed_data import DeployedDataService
from core.utils.permissions import SuperAdminRolePermission


def _parse_min_commune_detections(request) -> int:
    try:
        value = int(request.GET.get("minCommuneDetections") or 0)
    except ValueError:
        value = 0
    return max(value, 0)


class DeployedDataUserSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    email = serializers.EmailField()


class DeployedDataUserGroupSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    users = DeployedDataUserSerializer(many=True)


class DeployedDataCommuneSerializer(serializers.Serializer):
    # Per commune we count detection OBJECTS (not Detection rows); the per-tile-set
    # breakdown below counts detections.
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    detection_objects_count = serializers.IntegerField()
    detection_objects_in_custom_zone_count = serializers.IntegerField()


class DeployedDataCustomZoneSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    category_name = serializers.CharField(allow_null=True)
    color = serializers.CharField(allow_null=True)


class DeployedDataDetectionsByTileSetSerializer(serializers.Serializer):
    """Detection counts for one tile set (Detection.tile_set): total, and the subset
    whose detection object falls inside at least one custom zone — same criteria as the
    per-commune counts."""

    uuid = serializers.UUIDField()
    name = serializers.CharField()
    date = serializers.DateField()
    detections_count = serializers.IntegerField()
    detections_in_custom_zone_count = serializers.IntegerField()


class DeployedDataDepartmentSummarySerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    communes_with_detections_count = serializers.IntegerField()
    users_count = serializers.IntegerField()
    tile_set_years = serializers.ListField(child=serializers.CharField())


class DeployedDataDepartmentSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    parcels_count = serializers.IntegerField()
    sitadel_updated_parcels_count = serializers.IntegerField()
    communes_with_detections_count = serializers.IntegerField()
    communes = DeployedDataCommuneSerializer(many=True)
    user_groups = DeployedDataUserGroupSerializer(many=True)
    custom_zones = DeployedDataCustomZoneSerializer(many=True)
    detections_by_tile_set = DeployedDataDetectionsByTileSetSerializer(many=True)


class StatisticsDeployedDataView(APIView):
    """Per-department list of deployed data (lightweight rows). SUPER_ADMIN only.

    Query params:
    - `q`: search departments by name.
    - `minCommuneDetections`: exclude communes (from the count and the list) that have
      fewer than this many detections; departments left with no qualifying commune are
      dropped.

    Each row carries only what the list table needs; the full per-department breakdown
    is served by `StatisticsDeployedDataDetailView`.
    """

    permission_classes = [SuperAdminRolePermission]

    def get(self, request):
        q = request.GET.get("q") or None
        min_commune_detections = _parse_min_commune_detections(request)

        departments = DeployedDataService.get_departments_summary(
            q=q, min_commune_detections=min_commune_detections
        )
        serializer = DeployedDataDepartmentSummarySerializer(departments, many=True)
        # CamelCaseJSONRenderer (default) camelizes the snake_case keys on output.
        return Response(serializer.data)


class StatisticsDeployedDataDetailView(APIView):
    """Full deployed-data detail for a single department. SUPER_ADMIN only.

    Query params:
    - `minCommuneDetections`: same per-commune threshold as the list, so the detail's
      commune count/list stays consistent with the row that was clicked.
    """

    permission_classes = [SuperAdminRolePermission]

    def get(self, request, uuid):
        min_commune_detections = _parse_min_commune_detections(request)

        department = DeployedDataService.get_department_deployed_data(
            uuid=uuid, min_commune_detections=min_commune_detections
        )
        if department is None:
            raise NotFound("Department not found or not deployed.")

        serializer = DeployedDataDepartmentSerializer(department)
        # CamelCaseJSONRenderer (default) camelizes the snake_case keys on output.
        return Response(serializer.data)
