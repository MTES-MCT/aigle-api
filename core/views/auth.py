from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from core.serializers.auth import (
    CustomTokenObtainPairSerializer,
    MfaVerifyLinkSerializer,
)


class CustomTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    serializer_class = CustomTokenObtainPairSerializer


class MfaVerifyLinkView(APIView):
    """Échange le jeton du lien reçu par courriel contre une paire access/refresh."""

    permission_classes = [AllowAny]
    # Un jeton d'accès périmé encore présent côté client ne doit pas faire échouer
    # cette route en 401 avant même d'être lue.
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa"

    def post(self, request):
        serializer = MfaVerifyLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.validated_data)
