from django.http import JsonResponse

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated


from core.utils.filters import UuidInFilter


class EndpointSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    tile_set_uuids = UuidInFilter()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def endpoint(request):
    params_serializer = EndpointSerializer(data=request.GET)
    params_serializer.is_valid(raise_exception=True)

    return JsonResponse({"lat": "lat"})


URL = "get-tile/"
