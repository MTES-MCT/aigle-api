"""Tests for the DDTM activity statistics endpoints."""

from datetime import timedelta

from django.utils import timezone
from simple_history.utils import bulk_update_with_history

from core.models.analytic_log import AnalyticLog, AnalyticLogType
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionValidationStatus,
)
from core.models.user_group import UserGroupType
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_object,
)
from core.tests.fixtures.geo_data import (
    create_gard_department,
    create_herault_department,
    create_montpellier_commune,
    create_nimes_commune,
)
from core.tests.fixtures.users import (
    add_user_to_group,
    create_super_admin,
    create_user,
    create_user_group,
)

SUMMARY_URL = "/api/statistics/ddtm-activity/"
GROUPS_URL = "/api/statistics/ddtm-activity/user-groups/"


def group_url(uuid):
    return f"/api/statistics/ddtm-activity/user-group/{uuid}/"


def users_url(uuid):
    return f"/api/statistics/ddtm-activity/user-group/{uuid}/users/"


def mid_month(months_ago=0):
    """An aware datetime pinned to the middle of a month: immune to test runs near
    month/window boundaries (months_ago=0 is always in the 30-day window)."""
    now = timezone.localtime()
    year, month = now.year, now.month - months_ago
    while month <= 0:
        year, month = year - 1, month + 12
    return now.replace(year=year, month=month, day=15, hour=12, minute=0)


def create_typed_group(name, geo_zones, group_type=UserGroupType.COLLECTIVITY):
    group = create_user_group(name=name, geo_zones=geo_zones)
    group.user_group_type = group_type
    group.save()
    return group


def create_analytic_log(user, log_type, when):
    log = AnalyticLog.objects.create(user=user, analytic_log_type=log_type)
    # created_at is auto_now_add; backdate through a queryset update.
    AnalyticLog.objects.filter(pk=log.pk).update(created_at=when)


def log_connection(user, when):
    create_analytic_log(user, AnalyticLogType.USER_ACCESS, when)


def set_last_login(user, when):
    # save() writes a User history row; _first_login_by_user reads MIN(last_login)
    # from that history (the creation row's last_login is NULL and is ignored).
    user.last_login = when
    user.save()


def create_controlled_detection_data(detection_object=None):
    """A DetectionData linked to a detection object, with its creation history row
    backdated so later backdated transitions stay ordered after it."""
    detection_data = DetectionData.objects.create(
        detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
        detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
    )
    if detection_object is None:
        detection_object = create_detection_object()
    create_detection(detection_object=detection_object, detection_data=detection_data)
    detection_data.history.all().update(
        history_date=timezone.now() - timedelta(days=700)
    )
    return detection_data


def change_control_status(detection_data, user, status, when):
    detection_data.set_detection_control_status(status)
    detection_data._history_user = user
    detection_data._history_date = when
    detection_data.save()


def single_action(user, status, when):
    """One operational action: a control-status transition on its own detection."""
    detection_data = create_controlled_detection_data()
    change_control_status(detection_data, user, status, when)


class DdtmActivityViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.herault = create_herault_department()
        self.gard = create_gard_department()
        self.montpellier = create_montpellier_commune(department=self.herault)
        self.nimes = create_nimes_commune(department=self.gard)

        self.ddtm_group = create_typed_group(
            "DDTM Hérault", [self.herault], UserGroupType.DDTM
        )
        self.ddtm_user = create_user(email="ddtm@test.com")
        add_user_to_group(self.ddtm_user, self.ddtm_group)

        # In scope: linked to a commune of Hérault.
        self.group_a = create_typed_group("Mairie Montpellier", [self.montpellier])
        self.group_b = create_typed_group("Métropole Montpellier", [self.montpellier])
        # Out of scope: commune of another department / the department zone itself.
        self.group_gard = create_typed_group("Mairie Nîmes", [self.nimes])
        self.group_dept_only = create_typed_group("Syndicat Hérault", [self.herault])

        # group_a members. Statuses (30-day window):
        #   alice: 7 actions, 0 connections           -> PILOT
        #   frank: 3 actions, 0 connections           -> INACTIVE (< 7 and no connection)
        #   bob:   1 action,  1 connection            -> ACTIVE
        #   carol: nothing                            -> INACTIVE
        # Excluded from every stat: dave (staff), eve (member of a DDTM group).
        self.alice = create_user(email="alice@test.com")
        self.bob = create_user(email="bob@test.com")
        self.carol = create_user(email="carol@test.com")
        self.frank = create_user(email="frank@test.com")
        self.dave_staff = create_user(email="dave@test.com", is_staff=True)
        self.eve_ddtm = create_user(email="eve@test.com")
        for user in (
            self.alice,
            self.bob,
            self.carol,
            self.frank,
            self.dave_staff,
            self.eve_ddtm,
        ):
            add_user_to_group(user, self.group_a)
        add_user_to_group(self.eve_ddtm, self.ddtm_group)
        # carol is also the only (idle) member of group_b.
        add_user_to_group(self.carol, self.group_b)

        # First logins (deployment date = earliest across a group's members). frank is
        # the earliest group_a member; staff/DDTM (dave, eve) log in even earlier but
        # must be excluded. carol never logs in.
        now = timezone.now()
        self.group_a_deployment = now - timedelta(weeks=10)  # frank's, the earliest
        set_last_login(self.alice, now - timedelta(weeks=5))
        set_last_login(self.bob, now - timedelta(weeks=3))
        set_last_login(self.frank, self.group_a_deployment)
        set_last_login(self.dave_staff, now - timedelta(weeks=100))
        set_last_login(self.eve_ddtm, now - timedelta(weeks=100))

        self._create_activity()

    def _create_activity(self):
        now_mid = mid_month(0)

        # Alice, PILOT: 6 single-object transitions + 1 bulk transition spanning 2
        # detection datas of ONE object (deduped to 1) = 7 actions.
        for i in range(6):
            single_action(
                self.alice,
                DetectionControlStatus.CONTROLLED_FIELD,
                now_mid + timedelta(minutes=i),
            )
        shared_object = create_detection_object()
        shared_data_1 = create_controlled_detection_data(detection_object=shared_object)
        shared_data_2 = create_controlled_detection_data(detection_object=shared_object)
        for detection_data in (shared_data_1, shared_data_2):
            detection_data.set_detection_control_status(
                DetectionControlStatus.PRIOR_LETTER_SENT
            )
            detection_data._history_date = now_mid
        bulk_update_with_history(
            [shared_data_1, shared_data_2],
            DetectionData,
            [
                "detection_control_status",
                "detection_validation_status",
                "detection_prescription_status",
            ],
            default_user=self.alice,
        )
        # A no-op save (status unchanged) must NOT count as an action.
        change_control_status(
            shared_data_1,
            self.alice,
            DetectionControlStatus.PRIOR_LETTER_SENT,
            now_mid + timedelta(hours=1),
        )
        # Alice also acted 2 months ago (outside the 30-day window, inside the chart).
        single_action(self.alice, DetectionControlStatus.TO_CONTROL, mid_month(2))

        # Frank, INACTIVE despite 3 actions (no connection, below the pilot threshold).
        for i in range(3):
            single_action(
                self.frank,
                DetectionControlStatus.CONTROLLED_FIELD,
                now_mid + timedelta(minutes=i),
            )

        # Bob, ACTIVE: 1 connection in window (+1 outside); 1 in-window transition
        # whose predecessor is OUTSIDE the window (still a real change).
        log_connection(self.bob, now_mid)
        log_connection(self.bob, mid_month(2))
        bob_data = create_controlled_detection_data()
        change_control_status(
            bob_data, self.bob, DetectionControlStatus.TO_CONTROL, mid_month(3)
        )
        change_control_status(
            bob_data, self.bob, DetectionControlStatus.CONTROLLED_FIELD, now_mid
        )

        # Report downloads this month: bob (counted) + dave (staff, excluded).
        create_analytic_log(self.bob, AnalyticLogType.REPORT_DOWNLOAD, now_mid)
        create_analytic_log(self.bob, AnalyticLogType.REPORT_DOWNLOAD, now_mid)
        create_analytic_log(self.dave_staff, AnalyticLogType.REPORT_DOWNLOAD, now_mid)

        # Excluded users are active, to prove their activity never leaks in.
        log_connection(self.dave_staff, now_mid)
        log_connection(self.eve_ddtm, now_mid)
        single_action(self.dave_staff, DetectionControlStatus.CONTROLLED_FIELD, now_mid)

    # ------------------------------------------------------------------ access

    def test_summary_unauthenticated(self):
        self.assertEqual(self.client.get(SUMMARY_URL).status_code, 401)

    def test_groups_unauthenticated(self):
        self.assertEqual(self.client.get(GROUPS_URL).status_code, 401)

    def test_monthly_unauthenticated(self):
        self.assertEqual(self.client.get(group_url(self.group_a.uuid)).status_code, 401)

    def test_users_unauthenticated(self):
        self.assertEqual(self.client.get(users_url(self.group_a.uuid)).status_code, 401)

    def test_forbidden_for_non_ddtm_member(self):
        self.authenticate_user(self.alice)
        self.assertEqual(self.client.get(SUMMARY_URL).status_code, 403)
        self.assertEqual(self.client.get(GROUPS_URL).status_code, 403)
        self.assertEqual(self.client.get(group_url(self.group_a.uuid)).status_code, 403)
        self.assertEqual(self.client.get(users_url(self.group_a.uuid)).status_code, 403)

    def test_forbidden_for_super_admin_without_ddtm_group(self):
        self.authenticate_user(create_super_admin())
        self.assertEqual(self.client.get(SUMMARY_URL).status_code, 403)
        self.assertEqual(self.client.get(GROUPS_URL).status_code, 403)
        self.assertEqual(self.client.get(users_url(self.group_a.uuid)).status_code, 403)

    # ----------------------------------------------------------------- summary

    def test_summary(self):
        self.authenticate_user(self.ddtm_user)
        response = self.client.get(SUMMARY_URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["departmentName"], "Hérault")
        # Groups linked to a commune of Hérault only: no Gard group, no
        # department-zone-only group, no DDTM group.
        self.assertEqual(data["userGroupsCount"], 2)
        self.assertEqual(
            sorted(group["name"] for group in data["userGroups"]),
            [self.group_a.name, self.group_b.name],
        )
        # Active group = has >= 1 member connected in the window. Only group_a (bob).
        self.assertEqual(data["activeUserGroupsCount"], 1)

    # ------------------------------------------------------------------- groups

    def test_groups_rows_scope_and_counts(self):
        self.authenticate_user(self.ddtm_user)
        response = self.client.get(GROUPS_URL)
        self.assertEqual(response.status_code, 200)
        rows = response.json()

        self.assertEqual(
            [row["name"] for row in rows], [self.group_a.name, self.group_b.name]
        )

        group_a = next(row for row in rows if row["name"] == self.group_a.name)
        # Staff (dave) and DDTM members (eve) are excluded.
        self.assertEqual(group_a["usersCount"], 4)
        self.assertEqual(group_a["pilotUsersCount"], 1)
        self.assertEqual(group_a["activeUsersCount"], 1)

    def test_groups_deployed_since_weeks(self):
        self.authenticate_user(self.ddtm_user)
        rows = self.client.get(GROUPS_URL).json()
        by_name = {row["name"]: row for row in rows}
        # Earliest first login across non-staff, non-DDTM members = frank at 10 weeks;
        # staff (dave) and DDTM (eve) logged in 100 weeks ago but are excluded.
        self.assertEqual(by_name[self.group_a.name]["deployedSinceWeeks"], 10)
        self.assertEqual(
            by_name[self.group_a.name]["deploymentDate"],
            timezone.localtime(self.group_a_deployment).date().isoformat(),
        )
        # group_b's only member (carol) never logged in.
        self.assertIsNone(by_name[self.group_b.name]["deployedSinceWeeks"])
        self.assertIsNone(by_name[self.group_b.name]["deploymentDate"])

    def test_group_users_detail_and_ordering(self):
        self.authenticate_user(self.ddtm_user)
        response = self.client.get(users_url(self.group_a.uuid))
        self.assertEqual(response.status_code, 200)
        users = response.json()

        # Ordered by actions desc, then connections desc, then email. This differs
        # from the alphabetical email order (alice, bob, carol, frank), so a sort
        # regression would be caught.
        self.assertEqual(
            [user["email"] for user in users],
            ["alice@test.com", "frank@test.com", "bob@test.com", "carol@test.com"],
        )
        # Each row carries the user uuid the frontend DataTable keys on.
        self.assertTrue(all(user["uuid"] for user in users))

        by_email = {user["email"]: user for user in users}
        # 6 single edits + 1 bulk (2 history rows on one object, deduped) = 7;
        # no-op rows and the 2-month-old action don't count.
        self.assertEqual(by_email["alice@test.com"]["operationalActionsCount"], 7)
        self.assertEqual(by_email["alice@test.com"]["connectionsCount"], 0)
        self.assertEqual(by_email["alice@test.com"]["activityStatus"], "PILOT")

        # 3 actions but no connection: below the pilot threshold -> INACTIVE.
        self.assertEqual(by_email["frank@test.com"]["operationalActionsCount"], 3)
        self.assertEqual(by_email["frank@test.com"]["connectionsCount"], 0)
        self.assertEqual(by_email["frank@test.com"]["activityStatus"], "INACTIVE")

        # Bob's out-of-window transition/connection don't count; the recent ones do.
        self.assertEqual(by_email["bob@test.com"]["operationalActionsCount"], 1)
        self.assertEqual(by_email["bob@test.com"]["connectionsCount"], 1)
        self.assertEqual(by_email["bob@test.com"]["activityStatus"], "ACTIVE")

        self.assertEqual(by_email["carol@test.com"]["operationalActionsCount"], 0)
        self.assertEqual(by_email["carol@test.com"]["connectionsCount"], 0)
        self.assertEqual(by_email["carol@test.com"]["activityStatus"], "INACTIVE")

    # ----------------------------------------------------------------- monthly

    def test_monthly_buckets(self):
        self.authenticate_user(self.ddtm_user)
        response = self.client.get(group_url(self.group_a.uuid))
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["name"], self.group_a.name)
        months = data["months"]
        self.assertEqual(len(months), 12)
        now = timezone.localtime()
        self.assertEqual(months[-1]["month"], f"{now.year:04d}-{now.month:02d}")

        # Current month: alice, frank and bob all acted (monthly pilot = >= 1 action);
        # carol did nothing.
        current = months[-1]
        self.assertEqual(current["pilotUsersCount"], 3)
        self.assertEqual(current["activeUsersCount"], 0)
        self.assertEqual(current["inactiveUsersCount"], 1)

        # Two months ago: alice acted, bob only connected; carol and frank nothing.
        two_months_ago = months[-3]
        self.assertEqual(two_months_ago["pilotUsersCount"], 1)
        self.assertEqual(two_months_ago["activeUsersCount"], 1)
        self.assertEqual(two_months_ago["inactiveUsersCount"], 2)

        # Oldest bucket: nobody was active — inactive == the 4 members.
        self.assertEqual(months[0]["pilotUsersCount"], 0)
        self.assertEqual(months[0]["activeUsersCount"], 0)
        self.assertEqual(months[0]["inactiveUsersCount"], 4)

    def test_monthly_control_status_changes(self):
        self.authenticate_user(self.ddtm_user)
        data = self.client.get(group_url(self.group_a.uuid)).json()
        changes = data["controlStatusChangesByMonth"]
        self.assertEqual(len(changes), 12)

        # Current month: CONTROLLED_FIELD on 10 distinct objects (alice 6 + frank 3 +
        # bob 1); PRIOR_LETTER_SENT on 1 object (alice's bulk, 2 detection datas deduped).
        # dave (staff) is excluded. No-op re-save doesn't add a change.
        current = {row["status"]: row["count"] for row in changes[-1]["counts"]}
        self.assertEqual(current, {"CONTROLLED_FIELD": 10, "PRIOR_LETTER_SENT": 1})
        # Two months ago: alice's single TO_CONTROL change.
        two_months_ago = {row["status"]: row["count"] for row in changes[-3]["counts"]}
        self.assertEqual(two_months_ago, {"TO_CONTROL": 1})

    def test_monthly_report_downloads_and_connections(self):
        self.authenticate_user(self.ddtm_user)
        data = self.client.get(group_url(self.group_a.uuid)).json()
        now = timezone.localtime()
        current_key = f"{now.year:04d}-{now.month:02d}"

        downloads = {
            row["month"]: row["count"] for row in data["reportDownloadsByMonth"]
        }
        connections = {row["month"]: row["count"] for row in data["connectionsByMonth"]}
        self.assertEqual(len(downloads), 12)
        self.assertEqual(len(connections), 12)
        # bob's 2 report downloads this month; dave (staff) is excluded.
        self.assertEqual(downloads[current_key], 2)
        # bob's 1 connection this month; dave (staff) and eve (DDTM) are excluded.
        self.assertEqual(connections[current_key], 1)

    def test_group_detail_outside_department_is_not_found(self):
        self.authenticate_user(self.ddtm_user)
        for uuid in (
            self.group_gard.uuid,
            self.group_dept_only.uuid,
            self.ddtm_group.uuid,
        ):
            self.assertEqual(self.client.get(group_url(uuid)).status_code, 404)
            self.assertEqual(self.client.get(users_url(uuid)).status_code, 404)


class DdtmActivityOrderingTests(BaseAPITestCase):
    """Isolated fixture so all members share the same action count, exercising the
    secondary sort keys (connections desc, then email) that the main scenario's
    distinct action counts never reach."""

    def setUp(self):
        super().setUp()
        herault = create_herault_department()
        montpellier = create_montpellier_commune(department=herault)

        self.ddtm_group = create_typed_group(
            "DDTM Hérault", [herault], UserGroupType.DDTM
        )
        self.ddtm_user = create_user(email="ddtm@test.com")
        add_user_to_group(self.ddtm_user, self.ddtm_group)

        self.group = create_typed_group("Mairie", [montpellier])
        now_mid = mid_month(0)

        # All three have 2 operational actions, so the primary key is a tie:
        #   zoe : 2 actions, 5 connections
        #   amy : 2 actions, 5 connections   (tie on actions AND connections -> email asc)
        #   mid : 2 actions, 2 connections   (fewer connections -> ranked after both)
        # Expected order: amy, zoe (email tiebreak), then mid (connections tiebreak).
        for email, connections in (
            ("zoe@test.com", 5),
            ("amy@test.com", 5),
            ("mid@test.com", 2),
        ):
            user = create_user(email=email)
            add_user_to_group(user, self.group)
            for i in range(2):
                single_action(
                    user,
                    DetectionControlStatus.CONTROLLED_FIELD,
                    now_mid + timedelta(minutes=i),
                )
            for _ in range(connections):
                log_connection(user, now_mid)

    def test_user_ordering_secondary_tiebreakers(self):
        self.authenticate_user(self.ddtm_user)
        users = self.client.get(users_url(self.group.uuid)).json()
        self.assertEqual(
            [user["email"] for user in users],
            ["amy@test.com", "zoe@test.com", "mid@test.com"],
        )
