from rest_framework.views import APIView
from rest_framework.response import Response


class MapSettingsView(APIView):
    def get(self, request):
        from core.services.map_settings import MapSettingsService

        service = MapSettingsService(user=request.user)
        response_data = service.build_settings()

        return Response(response_data)
