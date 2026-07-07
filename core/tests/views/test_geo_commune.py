import uuid

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import create_super_admin


class GeoCommuneViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        self.montpellier = self.geo_data["communes"]["montpellier"]
        self.herault = self.geo_data["departments"]["herault"]

        self.user = create_super_admin(email="testgeo@example.com")
        self.authenticate_user(self.user)

    def test_list_communes_authenticated(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 8)

    def test_list_communes_unauthenticated(self):
        self.unauthenticate()
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_commune_detail(self):
        url = reverse(
            "GeoCommuneViewSet-detail", kwargs={"uuid": str(self.montpellier.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Montpellier")
        self.assertEqual(response.data["code"], "34172")

    def test_search_commune_by_exact_name(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url, {"q": "Montpellier"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        commune_names = [r["name"] for r in response.data]
        self.assertIn("Montpellier", commune_names)

    def test_search_commune_by_partial_name(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url, {"q": "Montpe"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        commune_names = [r["name"] for r in response.data]
        self.assertIn("Montpellier", commune_names)

    def test_search_commune_by_iso_code(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url, {"q": "34172"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data), 0)
        self.assertEqual(response.data[0]["code"], "34172")

    def test_search_commune_case_insensitive(self):
        url = reverse("GeoCommuneViewSet-list")
        response_lower = self.client.get(url, {"q": "montpellier"})
        response_upper = self.client.get(url, {"q": "MONTPELLIER"})

        self.assertEqual(response_lower.status_code, status.HTTP_200_OK)
        self.assertEqual(response_upper.status_code, status.HTTP_200_OK)

        results_lower = [r["name"] for r in response_lower.data]
        results_upper = [r["name"] for r in response_upper.data]

        self.assertIn("Montpellier", results_lower)
        self.assertIn("Montpellier", results_upper)

    def test_communes_ordered_by_iso_code(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        iso_codes = [r["code"] for r in response.data]
        self.assertEqual(iso_codes, sorted(iso_codes))

    def test_retrieve_nonexistent_commune_returns_404(self):
        fake_uuid = uuid.uuid4()
        url = reverse("GeoCommuneViewSet-detail", kwargs={"uuid": str(fake_uuid)})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_communes_returns_list(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    def test_search_returns_best_match_first(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url, {"q": "Paris"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data), 0)
        self.assertTrue(response.data[0]["name"].startswith("Paris"))

    def test_search_across_regions(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url, {"q": "Boulogne"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data), 0)
        commune_names = [r["name"] for r in response.data]
        self.assertIn("Boulogne-Billancourt", commune_names)

    def test_codes_filter_returns_exact_matches(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url, {"codes": "34172,34032"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({r["code"] for r in response.data}, {"34172", "34032"})

    def test_codes_filter_ignores_unknown_codes(self):
        # Unknown codes are simply absent from the result; the caller computes rejects.
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url, {"codes": "34172, 00000 ,34032"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({r["code"] for r in response.data}, {"34172", "34032"})

    def test_codes_filter_empty_returns_nothing(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url, {"codes": " , "})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_uuids_filter_resolves_entities_with_their_codes(self):
        # Backs raw mode: uuids in -> entities (so the caller can read their codes).
        beziers = self.geo_data["communes"]["beziers"]
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(
            url, {"uuids": f"{self.montpellier.uuid},{beziers.uuid}"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {r["uuid"] for r in response.data},
            {str(self.montpellier.uuid), str(beziers.uuid)},
        )
        self.assertEqual({r["code"] for r in response.data}, {"34172", "34032"})

    def test_uuids_filter_invalid_uuid_returns_400(self):
        url = reverse("GeoCommuneViewSet-list")
        response = self.client.get(url, {"uuids": "not-a-uuid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
