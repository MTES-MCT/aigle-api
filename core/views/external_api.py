from datetime import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_api_key.permissions import HasAPIKey

from core.serializers.external_api import UpdateControlStatusExternalApiInputSerializer
from core.services.external_api import ExternalApiService


class ExternalAPITestView(APIView):
    """
    Test endpoint for API key authentication.

    GET: Returns a success message with timestamp
    POST: Echoes back the received data

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


class ExternalAPIUpdateControlStatusView(APIView):
    """
    Update control status for detections on a specific parcel.

    This endpoint requires a valid API key in the Authorization header.
    Use: Authorization: Api-Key YOUR_API_KEY_HERE
    """

    permission_classes = [HasAPIKey]

    def post(self, request):
        serializer = UpdateControlStatusExternalApiInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        parcel_section, parcel_number = serializer.get_parcel_parts()

        ExternalApiService.update_control_status(
            insee_code=serializer.data["insee_code"],
            parcel_section=parcel_section,
            parcel_number=parcel_number,
            control_status=serializer.data["control_status"],
        )

        return Response(
            {
                "message": "Control status updated successfully",
                "status": "success",
            },
            status=status.HTTP_200_OK,
        )
