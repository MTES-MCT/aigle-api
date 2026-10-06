from unittest.mock import patch

from django.urls import reverse
from rest_framework import status

from core.models import UserRole
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_regular_user, create_user

PASSWORD = "Password123!"
INVALID_CREDENTIALS_BODY = {
    "nonFieldErrors": ["Aucun compte actif trouvé avec ces identifiants."],
    "code": "INVALID_CREDENTIALS",
}
ACCOUNT_INACTIVE_BODY = {
    "nonFieldErrors": ["Ce compte est inactif."],
    "code": "ACCOUNT_INACTIVE",
}
ACCOUNT_DEACTIVATED_BODY = {
    "nonFieldErrors": ["Votre compte est désactivé."],
    "code": "ACCOUNT_DEACTIVATED",
}


class LoginErrorBodyTests(BaseAPITestCase):
    """The login form keys its message on body.code; body.nonFieldErrors keeps the
    French message. Asserted on the rendered JSON (camelCase renderer + DRF exception
    handler), which is what the frontend reads."""

    def setUp(self):
        super().setUp()
        self.user = create_regular_user(email="login@test.com", password=PASSWORD)

    def _login(self, email, password):
        return self.client.post(
            reverse("jwt-create"), {"email": email, "password": password}, format="json"
        )

    def assert_login_error(self, email, password, expected_body):
        response = self._login(email, password)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), expected_body)

    def test_wrong_password(self):
        self.assert_login_error(self.user.email, "wrong", INVALID_CREDENTIALS_BODY)

    def test_unknown_email(self):
        self.assert_login_error("nobody@test.com", PASSWORD, INVALID_CREDENTIALS_BODY)

    def test_deactivated_role(self):
        # Deactivating a user sets the role only, is_active stays True.
        deactivated = create_user(
            email="login-deactivated@test.com",
            password=PASSWORD,
            user_role=UserRole.DEACTIVATED,
        )

        self.assert_login_error(deactivated.email, PASSWORD, ACCOUNT_DEACTIVATED_BODY)

    def test_inactive_account(self):
        # ModelBackend.authenticate() returns None for is_active=False, so this branch
        # is only reachable through a backend that lets inactive users through.
        self.user.is_active = False

        with patch("core.serializers.auth.authenticate", return_value=self.user):
            self.assert_login_error(self.user.email, PASSWORD, ACCOUNT_INACTIVE_BODY)

    def test_inactive_account_with_the_default_backend(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        self.assert_login_error(self.user.email, PASSWORD, INVALID_CREDENTIALS_BODY)

    def test_valid_credentials(self):
        response = self._login(self.user.email, PASSWORD)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.json()), {"access", "refresh"})


class TokenLoginRouteTests(BaseAPITestCase):
    """/auth/token/login/ was a second credential check the frontend never called:
    it answered 500 on success (rest_framework.authtoken is not installed)."""

    def test_route_is_gone(self):
        user = create_regular_user(email="token-login@test.com", password=PASSWORD)

        response = self.client.post(
            "/auth/token/login/",
            {"email": user.email, "password": PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
