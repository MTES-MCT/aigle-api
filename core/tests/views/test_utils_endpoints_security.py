"""Non-régression sur les vues de `core/views/utils/`.

Trois d'entre elles déclaraient `IsAuthenticated` au lieu du défaut applicatif
`IsActiveAuthenticated`, laissant un compte DEACTIVATED les atteindre jusqu'à
l'expiration de son JWT ; `get-custom-geometry` ne filtrait pas les zones à enjeux par
groupe ; `contact-us` échappait entièrement à DRF (ni quota, ni corps de requête).
"""

from unittest.mock import patch

from rest_framework import status

from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneStatus,
    GeoCustomZoneType,
)
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import (
    create_user,
    create_super_admin,
    create_user_with_group,
)
from core.models.user import UserRole

DEACTIVATED_CLOSED_URLS = [
    "utils/get-tile/",
    "utils/get-annotation-grid/",
    "utils/get-custom-geometry/",
]


class DeactivatedAccountLockoutTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        # Désactiver un compte bascule `user_role`, jamais `is_active` : le JWT reste
        # donc authentifiable jusqu'à son expiration, et seule la permission ferme.
        self.deactivated = create_user(
            email="deact-utils@test.com", user_role=UserRole.DEACTIVATED
        )

    def test_deactivated_account_is_locked_out_of_utils_endpoints(self):
        # Le JWT reste valide jusqu'à une heure après la désactivation : c'est la
        # permission, pas l'authentification, qui doit fermer la porte.
        self.authenticate_user(self.deactivated)

        for url in DEACTIVATED_CLOSED_URLS:
            with self.subTest(url=url):
                response = self.client.get(f"/api/{url}")
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_deactivated_account_is_locked_out_of_prior_letter(self):
        self.authenticate_user(self.deactivated)

        response = self.client.get(
            "/api/utils/generate-prior-letter/" "00000000-0000-0000-0000-000000000000/"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CustomGeometryScopeTests(BaseAPITestCase):
    """La bbox était le seul filtre : n'importe quelle zone à enjeux du territoire
    pouvait être rendue (nom, couleur, type, géométrie)."""

    URL = "/api/utils/get-custom-geometry/"
    BBOX = {"swLng": 3.80, "swLat": 43.55, "neLng": 3.96, "neLat": 43.68}

    def _create_zone(self, name, color, group=None):
        zone = GeoCustomZone.objects.create(
            name=name,
            color=color,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
            geo_custom_zone_type=GeoCustomZoneType.COMMON,
            geometry=self.create_bbox_polygon(3.85, 43.58, 3.92, 43.65),
        )
        if group is not None:
            group.geo_custom_zones.add(zone)
        return zone

    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        self.user, self.group, _ = create_user_with_group(
            email="cg-scope@test.com",
            group_name="Zones group",
            geo_zones=[self.geo_data["communes"]["montpellier"]],
        )
        self.granted_zone = self._create_zone(
            "Zone accordée", "#FF0000", group=self.group
        )
        self.other_zone = self._create_zone("Zone d'un autre groupe", "#00FF00")
        self.authenticate_user(self.user)

    def _names(self, response):
        return [
            feature["properties"]["name"]
            for feature in response.json()["customZones"]["features"]
        ]

    def test_zone_of_another_group_is_not_returned(self):
        response = self.client.get(
            self.URL,
            {
                **self.BBOX,
                "uuids": f"{self.granted_zone.uuid},{self.other_zone.uuid}",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = self._names(response)
        self.assertIn("Zone accordée", names)
        self.assertNotIn("Zone d'un autre groupe", names)

    def test_super_admin_still_sees_every_zone(self):
        self.authenticate_user(create_super_admin(email="cg-sa@test.com"))

        response = self.client.get(
            self.URL,
            {
                **self.BBOX,
                "uuids": f"{self.granted_zone.uuid},{self.other_zone.uuid}",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Zone d'un autre groupe", self._names(response))


class ContactUsEndpointTests(BaseAPITestCase):
    URL = "/api/utils/contact-us/"

    PAYLOAD = {
        "collectivity": "Ville de Montpellier",
        "issue": "Cabanisation",
        "name": "Camille Martin",
        "job": "Instructeur",
        "phone": "0400000000",
        "email": "camille@example.org",
    }

    @patch("core.views.utils.contact_us.send_mail")
    def test_post_sends_the_mail(self, mock_send_mail):
        response = self.client.post(self.URL, self.PAYLOAD, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send_mail.assert_called_once()

    @patch("core.views.utils.contact_us.send_mail")
    def test_get_is_rejected(self, mock_send_mail):
        # L'état civil, le téléphone et l'adresse ne doivent plus transiter en query
        # string (journaux du proxy, historique du navigateur).
        response = self.client.get(self.URL, self.PAYLOAD)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        mock_send_mail.assert_not_called()

    @patch("core.views.utils.contact_us.send_mail")
    def test_invalid_payload_does_not_send_mail(self, mock_send_mail):
        response = self.client.post(
            self.URL, {**self.PAYLOAD, "email": "pas-une-adresse"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_send_mail.assert_not_called()


class CsvFormulaEscapingTests(BaseAPITestCase):
    """Injection de formule dans les exports CSV d'administration (CWE-1236).

    Le nom d'un groupe ou d'une zone est du texte libre validé sur la seule non-vacuité :
    un compte autorisé à en créer un pouvait y placer =HYPERLINK(...), exécuté à
    l'ouverture de l'export par un administrateur.
    """

    def test_formula_prefixes_are_neutralised_on_export(self):
        from core.utils.bulk_csv import escape_csv_formula

        payload = '=HYPERLINK("http://attaquant.example","clic")'
        for value in [payload, "+1", "-1", "@SUM(A1)", "\tx", "\rx"]:
            with self.subTest(value=value):
                self.assertEqual(escape_csv_formula(value), f"'{value}")

    def test_ordinary_values_are_untouched(self):
        from core.utils.bulk_csv import escape_csv_formula

        for value in ["Montpellier", "34172", "L'Hérault", ""]:
            with self.subTest(value=value):
                self.assertEqual(escape_csv_formula(value), value)

    def test_escaping_round_trips_through_import(self):
        # L'export d'un nom neutralisé doit se réimporter à l'identique.
        from core.utils.bulk_csv import escape_csv_formula, unescape_csv_formula

        for value in ["=SUM(A1)", "-Zone sud", "L'Hérault", "'citation", "Montpellier"]:
            with self.subTest(value=value):
                self.assertEqual(unescape_csv_formula(escape_csv_formula(value)), value)
