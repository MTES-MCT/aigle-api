import uuid

from django.urls import reverse
from rest_framework import status

from core.models.user import UserRole
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import (
    create_complete_geo_hierarchy,
    create_montpellier_mediterranee_epci,
    create_nimes_ales_epci,
)
from core.tests.fixtures.users import create_super_admin, create_user_with_group


class GeoEpciViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        self.herault = self.geo_data["departments"]["herault"]
        self.gard = self.geo_data["departments"]["gard"]
        self.montpellier = self.geo_data["communes"]["montpellier"]
        self.beziers = self.geo_data["communes"]["beziers"]
        self.nimes = self.geo_data["communes"]["nimes"]

        self.epci = create_montpellier_mediterranee_epci(
            department=self.herault, communes=[self.montpellier, self.beziers]
        )
        self.other_epci = create_nimes_ales_epci(
            department=self.gard, communes=[self.nimes]
        )

        self.user = create_super_admin(email="testepci@example.com")
        self.authenticate_user(self.user)

    def test_list_epcis_authenticated(self):
        response = self.client.get(reverse("GeoEpciViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.data]
        self.assertIn("Montpellier Méditerranée Métropole", names)
        self.assertIn("Nîmes Métropole", names)

    def test_list_epcis_unauthenticated(self):
        self.unauthenticate()
        response = self.client.get(reverse("GeoEpciViewSet-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_epci_detail_exposes_siren_as_code(self):
        response = self.client.get(
            reverse("GeoEpciViewSet-detail", kwargs={"uuid": str(self.epci.uuid)})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Montpellier Méditerranée Métropole")
        # The frontend's GeoCollectivity contract is `code`, whatever the column is.
        self.assertEqual(response.data["code"], "243400017")

    def test_retrieve_nonexistent_epci(self):
        response = self.client.get(
            reverse("GeoEpciViewSet-detail", kwargs={"uuid": str(uuid.uuid4())})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_epci_by_name(self):
        response = self.client.get(
            reverse("GeoEpciViewSet-list"), {"q": "Méditerranée"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.data], [self.epci.name])

    def test_search_epci_by_siren_code(self):
        response = self.client.get(reverse("GeoEpciViewSet-list"), {"q": "243400017"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["code"] for row in response.data], ["243400017"])

    def test_filter_by_codes(self):
        response = self.client.get(
            reverse("GeoEpciViewSet-list"), {"codes": "243400017"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["code"] for row in response.data], ["243400017"])

    def test_filter_by_uuids(self):
        response = self.client.get(
            reverse("GeoEpciViewSet-list"), {"uuids": str(self.epci.uuid)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["code"] for row in response.data], ["243400017"])

    def test_regular_user_cannot_create_epci(self):
        regular, _, _ = create_user_with_group(
            email="regular-epci@example.com",
            user_role=UserRole.REGULAR,
            group_name="Groupe EPCI lecture",
            geo_zones=[self.epci],
        )
        self.authenticate_user(regular)

        response = self.client.post(
            reverse("GeoEpciViewSet-list"),
            {"name": "Nouvelle EPCI", "code": "999999999"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_departments_uuids_filter_keeps_only_that_department_epcis(self):
        response = self.client.get(
            reverse("GeoEpciViewSet-list"), {"departmentsUuids": str(self.herault.uuid)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({row["code"] for row in response.data}, {"243400017"})

    def test_regions_uuids_filter_spans_the_whole_region(self):
        # Hérault and Gard are both in Occitanie: one region hop reaches both EPCIs.
        occitanie = self.geo_data["regions"]["occitanie"]
        response = self.client.get(
            reverse("GeoEpciViewSet-list"), {"regionsUuids": str(occitanie.uuid)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {row["code"] for row in response.data}, {"243400017", "243000643"}
        )


class GeoEpciScopeTests(BaseAPITestCase):
    """An EPCI-scoped group must see its own perimeter — and only it — on every geo
    list endpoint, in both directions of the hierarchy."""

    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        self.herault = self.geo_data["departments"]["herault"]
        self.gard = self.geo_data["departments"]["gard"]
        self.montpellier = self.geo_data["communes"]["montpellier"]
        self.beziers = self.geo_data["communes"]["beziers"]
        self.nimes = self.geo_data["communes"]["nimes"]

        self.epci = create_montpellier_mediterranee_epci(
            department=self.herault, communes=[self.montpellier, self.beziers]
        )
        self.other_epci = create_nimes_ales_epci(
            department=self.gard, communes=[self.nimes]
        )

        # ADMIN, so the department/region endpoints (AdminRolePermission) are readable.
        self.user, self.group, _ = create_user_with_group(
            email="epci-scoped@example.com",
            user_role=UserRole.ADMIN,
            group_name="Collectivité EPCI",
            geo_zones=[self.epci],
        )
        self.authenticate_user(self.user)

    def test_sees_its_own_epci_only(self):
        response = self.client.get(reverse("GeoEpciViewSet-list"), {"q": "é"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [row["code"] for row in response.data]
        self.assertIn("243400017", codes)
        self.assertNotIn("243000643", codes)

    def test_sees_the_communes_of_its_epci_only(self):
        response = self.client.get(reverse("GeoCommuneViewSet-list"), {"q": "e"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.data]
        self.assertCountEqual(names, ["Montpellier", "Béziers"])

    def test_sees_the_parent_department_of_its_epci(self):
        response = self.client.get(reverse("GeoDepartmentViewSet-list"), {"q": "a"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.data]
        self.assertIn("Hérault", names)
        self.assertNotIn("Gard", names)

    def test_sees_the_parent_region_of_its_epci_once(self):
        response = self.client.get(reverse("GeoRegionViewSet-list"), {"q": "o"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.data]
        # Exactly once: the region is reached through a multi-valued join.
        self.assertEqual(names.count("Occitanie"), 1)
        self.assertNotIn("Île-de-France", names)

    def test_a_department_scoped_group_sees_that_departments_epcis(self):
        user, _, _ = create_user_with_group(
            email="dept-scoped@example.com",
            user_role=UserRole.ADMIN,
            group_name="DDTM Hérault",
            geo_zones=[self.herault],
        )
        self.authenticate_user(user)

        response = self.client.get(reverse("GeoEpciViewSet-list"), {"q": "é"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [row["code"] for row in response.data]
        self.assertEqual(codes, ["243400017"])

    def test_a_commune_scoped_group_sees_its_epci(self):
        user, _, _ = create_user_with_group(
            email="commune-scoped@example.com",
            user_role=UserRole.ADMIN,
            group_name="Commune Montpellier",
            geo_zones=[self.montpellier],
        )
        self.authenticate_user(user)

        response = self.client.get(reverse("GeoEpciViewSet-list"), {"q": "é"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [row["code"] for row in response.data]
        self.assertEqual(codes, ["243400017"])
