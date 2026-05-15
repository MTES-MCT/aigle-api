from rest_framework.views import APIView
from rest_framework.response import Response

from core.utils.super_admin_scope import get_super_admin_scoped_user_group


class MapSettingsView(APIView):
    def get(self, request):
        from core.services.map_settings import MapSettingsService

        scoped_user_group = get_super_admin_scoped_user_group(request)
        service = MapSettingsService(
            user=request.user,
            scoped_user_group=scoped_user_group,
        )
        response_data = service.build_settings()

        return Response(response_data)
