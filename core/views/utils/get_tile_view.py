from django.http import JsonResponse

from rest_framework import serializers


from core.utils.filters import UuidInFilter


class EndpointSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    tile_set_uuids = UuidInFilter()


def endpoint(request):
    params_serializer = EndpointSerializer(data=request.GET)
    params_serializer.is_valid(raise_exception=True)

    return JsonResponse({"lat": "lat"})


URL = "get-tile/"
