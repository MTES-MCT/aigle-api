"""Connexion par simple couple identifiant/mot de passe.

Une 2FA par lien de connexion envoyé par courriel a été ajoutée puis retirée : le login
renvoyait alors `{"mfaRequired": true}` sans aucun jeton. Ces tests verrouillent le
retour au comportement direct, et l'absence de toute route de second facteur.
"""

from django.urls import NoReverseMatch, reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_admin,
    create_deactivated_user,
    create_regular_user,
    create_super_admin,
)

PASSWORD = "userpass123"


class LoginTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.user = create_regular_user(email="login@test.com", password=PASSWORD)

    def login(self, email, password=PASSWORD):
        return self.client.post(
            reverse("jwt-create"), {"email": email, "password": password}, format="json"
        )

    def test_login_returns_both_tokens_directly(self):
        response = self.login(self.user.email)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_never_asks_for_a_second_factor(self):
        # Le rendu JSON est camelisé, la réponse brute reste en snake_case : on vérifie
        # les deux formes plutôt qu'une seule.
        response = self.login(self.user.email)

        self.assertNotIn("mfa_required", response.data)
        self.assertNotIn("mfaRequired", response.json())

    def test_admin_roles_also_log_in_directly(self):
        """Les rôles ADMIN et SUPER_ADMIN étaient soumis au second facteur sans condition."""
        for user in [
            create_admin(email="admin-login@test.com", password=PASSWORD),
            create_super_admin(email="super-login@test.com", password=PASSWORD),
        ]:
            with self.subTest(user_role=user.user_role):
                response = self.login(user.email)

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn("access", response.data)

    def test_login_sends_no_email(self):
        from django.core import mail

        mail.outbox = []
        self.login(self.user.email)

        self.assertEqual(mail.outbox, [])

    def test_wrong_password_is_rejected(self):
        response = self.login(self.user.email, password="mauvais-mot-de-passe")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access", response.data)

    def test_deactivated_account_is_rejected(self):
        deactivated = create_deactivated_user(
            email="deactivated-login@test.com", password=PASSWORD
        )

        response = self.login(deactivated.email)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access", response.data)

    def test_mfa_verify_link_route_is_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse("mfa-verify-link")

        response = self.client.post(
            "/auth/mfa/verify-link/", {"token": "peu-importe"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
