from datetime import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_api_key.permissions import HasAPIKey


class ExternalAPITestView(APIView):
    """
    This endpoint requires a valid API key in the Authorization header.
    Use: Authorization: Api-Key YOUR_API_KEY_HERE
    """

    permission_classes = [HasAPIKey]

    def get(self, request):
        return Response(
            {
                "message": "Successfully authenticated with API key",
                "status": "success",
                "data": {"timestamp": datetime.now()},
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        data = request.data

        return Response(
            {
                "message": "Data received successfully",
                "status": "success",
                "received_data": data,
            },
            status=status.HTTP_201_CREATED,
        )
