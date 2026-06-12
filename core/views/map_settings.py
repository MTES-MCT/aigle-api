from rest_framework.views import APIView
from rest_framework.response import Response

from core.permissions.scope import resolve_scoped_user_group


class MapSettingsView(APIView):
    def get(self, request):
        from core.services.map_settings import MapSettingsService

        service = MapSettingsService(
            user=request.user,
            scoped_user_group=resolve_scoped_user_group(request),
        )
        response_data = service.build_settings()

        return Response(response_data)
