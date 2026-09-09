"""Double authentification par lien de connexion envoyé par courriel."""

import re
from smtplib import SMTPException
from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from core.models.email import Email, EmailType
from core.models.user import UserRole
from core.models.user_group import FeatureFlag
from core.services.mfa import STORED_MESSAGE
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    add_user_to_group,
    create_admin,
    create_regular_user,
    create_super_admin,
    create_user_group,
)
from core.utils import mfa_challenge

LINK_BASE_URL = "https://aigle.test/login/verify/"
PASSWORD = "userpass123"


def extract_token(message) -> str:
    match = re.search(rf"{re.escape(LINK_BASE_URL)}(\S+)", message.body)
    assert match, f"aucun lien trouvé dans :\n{message.body}"
    return match.group(1)


@override_settings(MFA_ENABLED=True, MFA_LOGIN_LINK_BASE_URL=LINK_BASE_URL)
class MfaLoginTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.user = create_regular_user(email="agent@example.com", password=PASSWORD)
        self.group = create_user_group(name="DDTM 34")
        self.group.feature_flags = [FeatureFlag.REQUIRE_2FA]
        self.group.save()
        add_user_to_group(self.user, self.group)
        mail.outbox = []

    def login(self, email=None, password=PASSWORD):
        return self.client.post(
            reverse("jwt-create"),
            {"email": email or self.user.email, "password": password},
            format="json",
        )

    def verify(self, token):
        return self.client.post(
            reverse("mfa-verify-link"), {"token": token}, format="json"
        )

    def test_login_returns_no_token_and_sends_link(self):
        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["mfaRequired"])
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(LINK_BASE_URL, mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    def test_link_exchanges_for_tokens(self):
        self.login()
        response = self.verify(extract_token(mail.outbox[0]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_issued_token_actually_opens_a_business_route(self):
        self.login()
        access = self.verify(extract_token(mail.outbox[0])).data["access"]

        self.client.credentials(HTTP_AUTHORIZATION=f"JWT {access}")
        response = self.client.get("/api/users/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_link_is_single_use(self):
        self.login()
        token = extract_token(mail.outbox[0])

        self.assertEqual(self.verify(token).status_code, status.HTTP_200_OK)
        self.assertEqual(self.verify(token).status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_token_is_rejected(self):
        self.assertEqual(
            self.verify("nawak-nawak-nawak").status_code, status.HTTP_400_BAD_REQUEST
        )

    def test_expired_challenge_is_rejected(self):
        self.login()
        token = extract_token(mail.outbox[0])

        # Le défi vit dans le cache : le purger équivaut à l'expiration du TTL.
        mfa_challenge.cache.clear()

        self.assertEqual(self.verify(token).status_code, status.HTTP_400_BAD_REQUEST)

    def test_bad_password_sends_nothing(self):
        response = self.login(password="wrong-password")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)

    def test_account_deactivated_after_link_sent_cannot_use_it(self):
        self.login()
        token = extract_token(mail.outbox[0])

        self.user.user_role = UserRole.DEACTIVATED
        self.user.save()

        self.assertEqual(self.verify(token).status_code, status.HTTP_400_BAD_REQUEST)

    def test_link_secret_is_not_persisted_in_email_table(self):
        self.login()
        token = extract_token(mail.outbox[0])

        stored = Email.objects.filter(email_type=EmailType.MFA_LOGIN_LINK).first()
        self.assertIsNotNone(stored)
        self.assertEqual(stored.message, STORED_MESSAGE)
        self.assertNotIn(token, stored.message)

    def test_failed_send_does_not_consume_the_quota(self):
        """Une panne SMTP ne doit pas verrouiller le compte une heure pour rien."""
        with patch(
            "core.services.mfa.send_mail", side_effect=SMTPException("smtp down")
        ):
            for _ in range(mfa_challenge.MAX_LINKS_PER_HOUR + 2):
                self.assertEqual(
                    self.login().status_code, status.HTTP_503_SERVICE_UNAVAILABLE
                )

        # Le SMTP revient : le compte doit pouvoir se connecter immédiatement.
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

    def test_link_quota_is_capped_per_account(self):
        for _ in range(mfa_challenge.MAX_LINKS_PER_HOUR):
            self.assertEqual(self.login().status_code, status.HTTP_200_OK)

        response = self.login()
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(len(mail.outbox), mfa_challenge.MAX_LINKS_PER_HOUR)


@override_settings(MFA_ENABLED=True, MFA_LOGIN_LINK_BASE_URL=LINK_BASE_URL)
class MfaPolicyTests(BaseAPITestCase):
    def login(self, user):
        return self.client.post(
            reverse("jwt-create"),
            {"email": user.email, "password": PASSWORD},
            format="json",
        )

    def setUp(self):
        super().setUp()
        mail.outbox = []

    def test_group_without_flag_logs_in_directly(self):
        user = create_regular_user(email="plain@example.com", password=PASSWORD)
        add_user_to_group(user, create_user_group(name="Sans 2FA"))

        response = self.login(user)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertEqual(len(mail.outbox), 0)

    def test_admin_is_always_required_even_without_group(self):
        response = self.login(create_admin(email="chef@example.com", password=PASSWORD))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["mfaRequired"])
        self.assertNotIn("access", response.data)

    def test_super_admin_is_always_required_even_without_group(self):
        response = self.login(
            create_super_admin(email="boss@example.com", password=PASSWORD)
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["mfaRequired"])
        self.assertNotIn("access", response.data)

    @override_settings(MFA_ENABLED=False)
    def test_kill_switch_disables_everything(self):
        response = self.login(
            create_super_admin(email="boss2@example.com", password=PASSWORD)
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertEqual(len(mail.outbox), 0)
