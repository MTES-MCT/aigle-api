from django.urls import path
from djoser.views import UserViewSet
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from core.views.auth import CustomTokenObtainPairView, LogoutView, MfaVerifyLinkView

# djoser.urls monte le UserViewSet entier avec les permissions de djoser, qui ignorent
# user_role : POST /auth/users/ laissait n'importe quel compte authentifié créer un
# SUPER_ADMIN, et PATCH /auth/users/me/ s'auto-promouvoir ou se donner is_staff. Seules
# les routes mot de passe sont exposées ici ; la gestion des comptes passe par
# /api/users/ (AdminRolePermission + UserService, qui contrôlent le demandeur).
urlpatterns = [
    path("jwt/create/", CustomTokenObtainPairView.as_view(), name="jwt-create"),
    path("jwt/refresh/", TokenRefreshView.as_view(), name="jwt-refresh"),
    path("jwt/verify/", TokenVerifyView.as_view(), name="jwt-verify"),
    path("jwt/logout/", LogoutView.as_view(), name="jwt-logout"),
    path("mfa/verify-link/", MfaVerifyLinkView.as_view(), name="mfa-verify-link"),
    path(
        "users/reset_password/",
        UserViewSet.as_view({"post": "reset_password"}),
        name="user-reset-password",
    ),
    path(
        "users/reset_password_confirm/",
        UserViewSet.as_view({"post": "reset_password_confirm"}),
        name="user-reset-password-confirm",
    ),
    path(
        "users/set_password/",
        UserViewSet.as_view({"post": "set_password"}),
        name="user-set-password",
    ),
]
