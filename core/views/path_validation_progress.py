from rest_framework.response import Response
from rest_framework.views import APIView

from core.serializers.path_validation_progress import (
    PathValidationProgressInputSerializer,
    PathValidationProgressSerializer,
)
from core.services.path_validation_progress import PathValidationProgressService
from core.utils.permissions import IsActiveAuthenticated


class PathValidationProgressView(APIView):
    permission_classes = [IsActiveAuthenticated]

    def get(self, request):
        progress = PathValidationProgressService.get(user=request.user)
        return Response(PathValidationProgressSerializer(progress).data)

    def patch(self, request):
        serializer = PathValidationProgressInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        progress = PathValidationProgressService.apply(
            user=request.user, **serializer.validated_data
        )
        return Response(PathValidationProgressSerializer(progress).data)
