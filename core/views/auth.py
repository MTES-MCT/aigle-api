from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
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


class LogoutView(APIView):
    """Révoque le refresh token de la session (liste noire simplejwt).

    Sans cette route, se déconnecter ne faisait qu'effacer les jetons du navigateur :
    une copie du refresh token restait valable jusqu'à son expiration, sur un poste
    partagé comme après un vol. Le mot de passe changé ou le compte désactivé n'y
    changeaient rien non plus.

    AllowAny et sans authentification : un access token périmé ne doit pas empêcher de
    révoquer le refresh, et le corps de la requête porte à lui seul la preuve de
    possession du jeton à révoquer. Un jeton déjà révoqué, expiré ou illisible répond
    205 comme les autres — l'appelant n'a rien à en déduire, et la déconnexion côté
    client ne doit jamais échouer.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh = request.data.get("refresh")

        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                pass

        return Response(status=status.HTTP_205_RESET_CONTENT)
