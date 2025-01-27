from rest_framework import serializers


from core.utils.serializers import CommaSeparatedStringField, CommaSeparatedUUIDField


class StatisticsEndpointSerializer(serializers.Serializer):
    detectionValidationStatuses = CommaSeparatedStringField(required=False)
    tileSetsUuids = CommaSeparatedUUIDField()

    detectionControlStatuses = CommaSeparatedStringField(required=False)
    score = serializers.FloatField(required=False)
    objectTypesUuids = CommaSeparatedUUIDField(required=False)
    customZonesUuids = CommaSeparatedUUIDField(required=False)
    prescripted = serializers.BooleanField(required=False)

    communesUuids = CommaSeparatedUUIDField(required=False)
    departmentsUuids = CommaSeparatedUUIDField(required=False)
    regionsUuids = CommaSeparatedUUIDField(required=False)


def get_collectivities_uuids(endpoint_serializer: StatisticsEndpointSerializer):
    communes_uuids = endpoint_serializer.validated_data.get("communesUuids") or []
    departments_uuids = endpoint_serializer.validated_data.get("departmentsUuids") or []
    regions_uuids = endpoint_serializer.validated_data.get("regionsUuids") or []

    collectivities_uuids = communes_uuids + departments_uuids + regions_uuids

    return collectivities_uuids or None
