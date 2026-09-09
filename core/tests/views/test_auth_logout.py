"""Révocation des refresh tokens.

Jusqu'ici aucun jeton volé ne pouvait être invalidé sans faire tourner la clé secrète :
`token_blacklist` n'était pas installée, ROTATE/BLACKLIST n'étaient pas configurés et
aucune route de déconnexion n'existait. Changer son mot de passe ou désactiver un compte
ne coupait pas l'accès tant que le refresh token n'avait pas expiré.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_regular_user


class LogoutViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.user = create_regular_user(email="logout@test.com")
        self.refresh = str(RefreshToken.for_user(self.user))

    def test_logout_revokes_the_refresh_token(self):
        response = self.client.post(
            reverse("jwt-logout"), {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)

        refreshed = self.client.post(
            reverse("jwt-refresh"), {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(refreshed.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_still_works_before_logout(self):
        response = self.client.post(
            reverse("jwt-refresh"), {"refresh": self.refresh}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_logout_without_token_does_not_fail(self):
        # Une déconnexion côté client ne doit jamais échouer, et un jeton illisible ou
        # déjà révoqué ne doit rien apprendre à l'appelant.
        for payload in [{}, {"refresh": "pas-un-jeton"}]:
            with self.subTest(payload=payload):
                response = self.client.post(
                    reverse("jwt-logout"), payload, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)

    def test_logout_twice_is_idempotent(self):
        self.client.post(
            reverse("jwt-logout"), {"refresh": self.refresh}, format="json"
        )
        response = self.client.post(
            reverse("jwt-logout"), {"refresh": self.refresh}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)


class RefreshRotationTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.user = create_regular_user(email="rotate@test.com")
        self.refresh = str(RefreshToken.for_user(self.user))

    def test_refresh_rotates_and_blacklists_the_previous_token(self):
        first = self.client.post(
            reverse("jwt-refresh"), {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        rotated = first.data["refresh"]
        self.assertNotEqual(rotated, self.refresh)

        # Un refresh token volé n'est utilisable qu'une fois : sa réutilisation après le
        # rafraîchissement légitime du titulaire échoue.
        replayed = self.client.post(
            reverse("jwt-refresh"), {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(replayed.status_code, status.HTTP_401_UNAUTHORIZED)

        still_valid = self.client.post(
            reverse("jwt-refresh"), {"refresh": rotated}, format="json"
        )
        self.assertEqual(still_valid.status_code, status.HTTP_200_OK)
