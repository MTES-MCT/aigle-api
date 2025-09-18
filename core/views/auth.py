from rest_framework.permissions import AllowAny
from djoser.views import TokenCreateView
from rest_framework_simplejwt.views import TokenObtainPairView

from core.serializers.auth import (
    CustomTokenCreateSerializer,
    CustomTokenObtainPairSerializer,
)


class CustomTokenCreateView(TokenCreateView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenCreateSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
