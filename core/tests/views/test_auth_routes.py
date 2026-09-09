"""Non-régression sur la surface exposée par /auth/.

`include("djoser.urls")` montait tout le UserViewSet de djoser avec les permissions de
djoser, qui ignorent user_role : un REGULAR pouvait créer un SUPER_ADMIN et s'auto-
promouvoir. Ces tests verrouillent la surface réduite.
"""

from django.urls import NoReverseMatch, reverse
from rest_framework import status

from core.models.user import User, UserRole
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_regular_user


class AuthRoutesSurfaceTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.user = create_regular_user(email="regular@example.com")
        self.authenticate_user(self.user)

    def test_cannot_create_user_through_auth(self):
        response = self.client.post(
            "/auth/users/",
            {
                "email": "backdoor@example.com",
                "password": "An0ther-Str0ng-Pass!",
                "userRole": UserRole.SUPER_ADMIN,
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
        )
        self.assertFalse(User.objects.filter(email="backdoor@example.com").exists())

    def test_cannot_self_promote_through_auth_users_me(self):
        response = self.client.patch(
            "/auth/users/me/",
            {"userRole": UserRole.SUPER_ADMIN},
            format="json",
        )

        self.assertIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.user_role, UserRole.REGULAR)

    def test_cannot_grant_self_is_staff_through_auth_users_me(self):
        response = self.client.patch(
            "/auth/users/me/",
            {"isStaff": True},
            format="json",
        )

        self.assertIn(
            response.status_code,
            [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED],
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)

    def test_token_login_route_is_gone(self):
        """Seconde porte de login, qui contournerait entièrement la 2FA."""
        with self.assertRaises(NoReverseMatch):
            reverse("token_login")

        response = self.client.post(
            "/auth/token/login/",
            {"email": self.user.email, "password": "userpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_password_reset_routes_still_reachable(self):
        response = self.client.post(
            reverse("user-reset-password"),
            {"email": self.user.email},
            format="json",
        )

        self.assertIn(
            response.status_code,
            [status.HTTP_204_NO_CONTENT, status.HTTP_200_OK],
        )

    def test_user_role_is_read_only_on_current_user_serializer(self):
        """Défense en profondeur : même réexposée, la route ne pourrait rien promouvoir."""
        from core.serializers.user import UserSerializer

        serializer = UserSerializer(
            instance=self.user,
            data={"userRole": UserRole.SUPER_ADMIN},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("user_role", serializer.validated_data)
        self.assertNotIn("is_staff", serializer.validated_data)
        self.assertNotIn("deleted", serializer.validated_data)
