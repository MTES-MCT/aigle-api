"""An EPCI collectivity supervises its member communes exactly as a DDTM supervises its
department, so it gets the same dashboard: the territory-wide top part (stat tiles,
groups table, groups-activity chart) plus a bottom driven by a commune selector.

A commune-scoped collectivity supervises nothing and must keep the own-group view.
"""

from core.models.user_group import UserGroupType
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import (
    create_beziers_commune,
    create_gard_department,
    create_herault_department,
    create_montpellier_commune,
    create_montpellier_mediterranee_epci,
    create_nimes_ales_epci,
    create_nimes_commune,
)
from core.tests.fixtures.users import (
    add_user_to_group,
    create_super_admin,
    create_user,
    create_user_group,
)
from core.tests.views.test_ddtm_activity import create_typed_group

SUMMARY_URL = "/api/statistics/ddtm-activity/"
GROUPS_URL = "/api/statistics/ddtm-activity/user-groups/"
GROUPS_ACTIVITY_URL = "/api/statistics/ddtm-activity/groups-activity/"


def group_url(uuid):
    return f"/api/statistics/ddtm-activity/user-group/{uuid}/"


def users_url(uuid):
    return f"/api/statistics/ddtm-activity/user-group/{uuid}/users/"


class EpciStatisticsDashboardTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.herault = create_herault_department()
        self.gard = create_gard_department()
        self.montpellier = create_montpellier_commune(department=self.herault)
        self.beziers = create_beziers_commune(department=self.herault)
        self.nimes = create_nimes_commune(department=self.gard)

        self.epci = create_montpellier_mediterranee_epci(
            department=self.herault, communes=[self.montpellier, self.beziers]
        )
        self.other_epci = create_nimes_ales_epci(
            department=self.gard, communes=[self.nimes]
        )

        self.epci_group = create_typed_group("Collectivité EPCI", [self.epci])
        self.epci_user = create_user(email="epci-stats@test.com", password="pass123")
        add_user_to_group(self.epci_user, self.epci_group)

    # ------------------------------------------------------------------ top part

    def test_summary_reports_an_epci_perimeter(self):
        self.authenticate_user(self.epci_user)
        response = self.client.get(SUMMARY_URL)

        self.assertEqual(response.status_code, 200)
        # `epciName` is what makes the client render the territory dashboard;
        # `departmentName` stays null so a DDTM caller is still distinguishable.
        self.assertEqual(response.data["epci_name"], self.epci.name)
        self.assertIsNone(response.data["department_name"])

    def test_summary_covers_every_group_of_the_epci_and_nothing_else(self):
        commune_group = create_typed_group("Commune Béziers", [self.beziers])
        create_typed_group("Commune Nîmes", [self.nimes])

        self.authenticate_user(self.epci_user)
        response = self.client.get(SUMMARY_URL)

        self.assertEqual(response.status_code, 200)
        names = {group["name"] for group in response.data["user_groups"]}
        self.assertEqual(names, {self.epci_group.name, commune_group.name})
        self.assertEqual(response.data["user_groups_count"], 2)

    def test_groups_table_is_readable_by_an_epci_member(self):
        self.authenticate_user(self.epci_user)
        response = self.client.get(GROUPS_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["name"] for row in response.data], [self.epci_group.name])

    def test_groups_activity_chart_is_readable_by_an_epci_member(self):
        self.authenticate_user(self.epci_user)
        response = self.client.get(GROUPS_ACTIVITY_URL)

        self.assertEqual(response.status_code, 200)
        self.assertIn("activity_by_period", response.data)
        self.assertEqual(
            [group["name"] for group in response.data["groups"]],
            [self.epci_group.name],
        )

    # -------------------------------------------------- bottom: commune selector

    def test_summary_carries_the_communes_of_the_epci_for_the_selector(self):
        self.authenticate_user(self.epci_user)
        response = self.client.get(SUMMARY_URL)

        group = next(
            row
            for row in response.data["user_groups"]
            if row["name"] == self.epci_group.name
        )
        self.assertEqual(
            {commune["name"] for commune in group["communes"]},
            {"Montpellier", "Béziers"},
        )

    def test_an_epci_member_reads_the_charts_of_a_commune_group_inside_it(self):
        commune_group = create_typed_group("Commune Béziers", [self.beziers])

        self.authenticate_user(self.epci_user)
        response = self.client.get(group_url(commune_group.uuid))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], commune_group.name)

    def test_an_epci_member_cannot_read_a_group_outside_its_perimeter(self):
        outsider = create_typed_group("Commune Nîmes", [self.nimes])

        self.authenticate_user(self.epci_user)
        response = self.client.get(group_url(outsider.uuid))

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------ scoping

    def test_a_commune_collectivity_keeps_the_own_group_dashboard(self):
        commune_group = create_typed_group("Commune Montpellier", [self.montpellier])
        user = create_user(email="commune-stats@test.com", password="pass123")
        add_user_to_group(user, commune_group)

        self.authenticate_user(user)
        summary = self.client.get(SUMMARY_URL)

        self.assertEqual(summary.status_code, 200)
        self.assertIsNone(summary.data["department_name"])
        self.assertIsNone(summary.data["epci_name"])
        # No supervised territory -> the territory-wide endpoints stay closed.
        self.assertEqual(self.client.get(GROUPS_URL).status_code, 403)
        self.assertEqual(self.client.get(GROUPS_ACTIVITY_URL).status_code, 403)

    def test_per_user_detail_stays_ddtm_only(self):
        """The EPCI gets the territory-wide AGGREGATES, not its members' identities."""
        self.authenticate_user(self.epci_user)
        response = self.client.get(users_url(self.epci_group.uuid))

        self.assertEqual(response.status_code, 403)

    def test_a_ddtm_sees_the_epci_group_of_its_department(self):
        ddtm_group = create_typed_group(
            "DDTM Hérault", [self.herault], group_type=UserGroupType.DDTM
        )
        ddtm_user = create_user(email="ddtm-stats@test.com", password="pass123")
        add_user_to_group(ddtm_user, ddtm_group)

        self.authenticate_user(ddtm_user)
        response = self.client.get(SUMMARY_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["department_name"], self.herault.name)
        self.assertIsNone(response.data["epci_name"])
        self.assertIn(
            self.epci_group.name,
            {group["name"] for group in response.data["user_groups"]},
        )

    def test_a_ddtm_membership_wins_over_an_epci_one(self):
        """A user in both keeps the broader department dashboard."""
        ddtm_group = create_typed_group(
            "DDTM Hérault", [self.herault], group_type=UserGroupType.DDTM
        )
        add_user_to_group(self.epci_user, ddtm_group)

        self.authenticate_user(self.epci_user)
        response = self.client.get(SUMMARY_URL)

        self.assertEqual(response.data["department_name"], self.herault.name)
        self.assertIsNone(response.data["epci_name"])


class EpciStatisticsImpersonationTests(BaseAPITestCase):
    """A scoped SUPER_ADMIN acts AS the impersonated group, so the dashboard the client
    renders and the endpoints it may call must agree."""

    def setUp(self):
        super().setUp()
        self.herault = create_herault_department()
        self.montpellier = create_montpellier_commune(department=self.herault)
        self.beziers = create_beziers_commune(department=self.herault)
        self.epci = create_montpellier_mediterranee_epci(
            department=self.herault, communes=[self.montpellier, self.beziers]
        )
        self.epci_group = create_typed_group("Collectivité EPCI", [self.epci])
        self.commune_group = create_typed_group(
            "Commune Montpellier", [self.montpellier]
        )

        self.super_admin = create_super_admin(email="sa-stats@test.com")
        self.authenticate_user(self.super_admin)

    def _scoped(self, url, group):
        return self.client.get(url, HTTP_X_USER_GROUP_UUID=str(group.uuid))

    def test_impersonating_an_epci_group_gives_the_epci_dashboard(self):
        response = self._scoped(SUMMARY_URL, self.epci_group)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["epci_name"], self.epci.name)
        self.assertIsNone(response.data["department_name"])
        self.assertEqual(self._scoped(GROUPS_URL, self.epci_group).status_code, 200)

    def test_impersonating_a_commune_group_closes_the_territory_endpoints(self):
        response = self._scoped(SUMMARY_URL, self.commune_group)

        self.assertIsNone(response.data["epci_name"])
        self.assertIsNone(response.data["department_name"])
        self.assertEqual(self._scoped(GROUPS_URL, self.commune_group).status_code, 403)


class EpciStatisticsUserGroupSerializationTests(BaseAPITestCase):
    """A user group whose only zone is an EPCI must never be mistaken for a group with
    no perimeter — that is what used to send an EPCI collectivity to an empty selector."""

    def setUp(self):
        super().setUp()
        self.herault = create_herault_department()
        self.montpellier = create_montpellier_commune(department=self.herault)
        self.beziers = create_beziers_commune(department=self.herault)
        self.epci = create_montpellier_mediterranee_epci(
            department=self.herault, communes=[self.montpellier, self.beziers]
        )

    def test_a_group_mixing_a_commune_and_an_epci_lists_each_commune_once(self):
        group = create_user_group(name="Mixte", geo_zones=[self.epci, self.montpellier])
        group.user_group_type = UserGroupType.COLLECTIVITY
        group.save()
        user = create_user(email="mixed-stats@test.com", password="pass123")
        add_user_to_group(user, group)

        self.authenticate_user(user)
        response = self.client.get(SUMMARY_URL)

        communes = next(
            row for row in response.data["user_groups"] if row["name"] == "Mixte"
        )["communes"]
        names = [commune["name"] for commune in communes]
        self.assertEqual(sorted(names), ["Béziers", "Montpellier"])
        self.assertEqual(len(names), len(set(names)), "a commune was listed twice")
