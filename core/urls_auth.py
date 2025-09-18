from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from core.views.auth import CustomTokenCreateView, CustomTokenObtainPairView

urlpatterns = [
    path("jwt/create/", CustomTokenObtainPairView.as_view(), name="jwt-create"),
    path("jwt/refresh/", TokenRefreshView.as_view(), name="jwt-refresh"),
    path("jwt/verify/", TokenVerifyView.as_view(), name="jwt-verify"),
    path("token/login/", CustomTokenCreateView.as_view(), name="token_login"),
    path("", include("djoser.urls")),
]
