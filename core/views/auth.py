from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from djoser.views import TokenCreateView
from rest_framework_simplejwt.views import TokenObtainPairView

from core.serializers.auth import (
    CustomTokenCreateSerializer,
    CustomTokenObtainPairSerializer,
)


class CustomTokenCreateView(TokenCreateView):
    permission_classes = [AllowAny]
    # Rate-limit login attempts per client IP to blunt credential brute-forcing
    # (rate is the "login" scope in DEFAULT_THROTTLE_RATES).
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    serializer_class = CustomTokenCreateSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    serializer_class = CustomTokenObtainPairSerializer
