from datetime import date, timedelta
from unittest import mock

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.db import OperationalError, connection
from django.utils import timezone

from core.constants.control_plan import CONTROL_PLAN_HISTORY_CHANGE_REASON
from core.constants.geo import SRID
from core.models.control_plan import (
    ControlPlan,
    ControlPlanParcel,
    ControlPlanParcelObject,
    ControlPlanWave,
)
from core.models.detection import DetectionSource
from core.models.detection_authorization import DetectionAuthorization
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.tile_set import TileSetStatus, TileSetType
from core.models.user import UserRole
from core.models.user_action_log import UserActionLog
from core.models.user_group import FeatureFlag, UserGroupType
from core.permissions.detection import DetectionPermission
from core.permissions.scope import HEADER_NAME
from core.services.ddtm_activity import DdtmActivityService
from core.tests.fixtures.control_plan import (
    PARCEL_URL,
    PLAN_URL,
    WAVE_URL,
    ControlPlanTestCase,
)
from core.services.control_plan import ControlPlanService
from core.tests.fixtures.detection_data import (
    create_object_type_with_category,
    create_tile_set,
)
from core.tests.fixtures.geo_data import create_montpellier_mediterranee_epci
from core.tests.fixtures.users import (
    add_user_to_group,
    create_regular_user,
    create_user,
    create_user_group,
)


class ControlPlanAccessTests(ControlPlanTestCase):
    def test_unauthenticated_is_refused(self):
        self.assertEqual(self.client.get(PLAN_URL).status_code, 401)

    def test_a_user_without_the_flag_nor_internal_is_refused(self):
        outsider = create_regular_user(email="plan-outsider@test.com")
        add_user_to_group(
            outsider, create_user_group(name="Sans flag", geo_zones=[self.herault])
        )
        self.authenticate_user(outsider)

        self.assertEqual(self.client.get(PLAN_URL).status_code, 403)
        self.assertEqual(self.client.get(f"{PLAN_URL}groups/").status_code, 403)

    def test_a_member_of_a_flagged_group_sees_its_group(self):
        self.authenticate_user(self.writer)

        response = self.client.get(f"{PLAN_URL}groups/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "uuid": str(self.group.uuid),
                    "name": self.group.name,
                    "userGroupType": self.group.user_group_type,
                    "canEdit": True,
                    "activeControlPlanUuid": None,
                }
            ],
        )

    def test_an_internal_user_writes_on_a_group_without_the_flag(self):
        internal = create_user(email="plan-internal@test.com", is_staff=True)
        unflagged = create_user_group(name="Équipe test", geo_zones=[self.herault])
        unflagged.geo_custom_zones.add(self.zone_a)
        add_user_to_group(internal, unflagged)

        plan = self.create_plan(user=internal, user_group=unflagged)

        self.assertEqual(plan["userGroup"]["uuid"], str(unflagged.uuid))
        self.assertTrue(plan["canEdit"])

    def test_a_read_only_member_reads_but_cannot_write(self):
        plan = self.create_plan()
        self.authenticate_user(self.reader)

        response = self.client.get(f"{PLAN_URL}{plan['uuid']}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["canEdit"])

        response = self.client.post(f"{PLAN_URL}{plan['uuid']}/close/")
        self.assertEqual(response.status_code, 403)
        response = self.create_wave(plan["uuid"])
        self.assertEqual(response.status_code, 403)

    def test_write_on_another_group_does_not_open_this_one(self):
        plan = self.create_plan()
        other_group = create_user_group(name="Autre groupe", geo_zones=[self.herault])
        other_group.feature_flags = [FeatureFlag.PLAN_DE_CONTROLE]
        other_group.save()
        add_user_to_group(self.reader, other_group)
        self.authenticate_user(self.reader)

        response = self.client.patch(
            f"{PLAN_URL}{plan['uuid']}/", {"name": "Piraté"}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    def test_the_plan_of_another_group_is_not_found(self):
        plan = self.create_plan()
        stranger = create_regular_user(email="plan-stranger@test.com")
        other_group = create_user_group(name="Gard plan", geo_zones=[self.nimes])
        other_group.feature_flags = [FeatureFlag.PLAN_DE_CONTROLE]
        other_group.save()
        add_user_to_group(stranger, other_group)
        self.authenticate_user(stranger)

        self.assertEqual(self.client.get(f"{PLAN_URL}{plan['uuid']}/").status_code, 404)
        self.assertEqual(self.client.get(PLAN_URL).json(), [])

    def test_a_super_admin_acts_as_the_impersonated_group(self):
        plan = self.create_plan()
        super_admin = create_user(
            email="plan-super@test.com", user_role=UserRole.SUPER_ADMIN
        )
        self.authenticate_user(super_admin)

        response = self.client.get(
            f"{PLAN_URL}{plan['uuid']}/", **{HEADER_NAME: str(self.group.uuid)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["canEdit"])

        unflagged = create_user_group(
            name="Groupe non flaggé", geo_zones=[self.herault]
        )
        response = self.client.get(PLAN_URL, **{HEADER_NAME: str(unflagged.uuid)})
        self.assertEqual(response.status_code, 403)


class ControlPlanLifecycleTests(ControlPlanTestCase):
    def test_one_active_plan_per_group(self):
        self.create_plan()

        response = self.client.post(
            PLAN_URL,
            {
                "userGroupUuid": str(self.group.uuid),
                "name": "Doublon",
                "startDate": "2026-01-01",
                "endDate": "2026-12-31",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_the_period_must_end_after_it_starts(self):
        self.authenticate_user(self.writer)
        response = self.client.post(
            PLAN_URL,
            {
                "userGroupUuid": str(self.group.uuid),
                "name": "Plan",
                "startDate": "2026-12-31",
                "endDate": "2026-01-01",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("endDate", response.json())

    def test_closing_frees_the_group_for_a_new_plan(self):
        plan = self.create_plan()

        response = self.client.post(f"{PLAN_URL}{plan['uuid']}/close/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["controlPlanStatus"], "CLOSED")
        self.assertFalse(response.json()["canEdit"])
        self.create_plan()

    def test_an_expired_plan_says_so(self):
        plan = self.create_plan()
        ControlPlan.objects.filter(uuid=plan["uuid"]).update(
            end_date=timezone.localdate() - timedelta(days=1),
            start_date=timezone.localdate() - timedelta(days=30),
        )

        response = self.client.get(f"{PLAN_URL}{plan['uuid']}/")

        self.assertTrue(response.json()["isExpired"])

    def test_a_plan_is_deleted_only_before_its_first_validation(self):
        parcel = self.make_parcel()
        self.make_object(parcel)

        plan = self.create_plan()
        response = self.client.delete(f"{PLAN_URL}{plan['uuid']}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get(PLAN_URL).json(), [])

        plan, _ = self.plan_and_validate()
        response = self.client.delete(f"{PLAN_URL}{plan['uuid']}/")
        self.assertEqual(response.status_code, 409)

    def test_a_group_without_active_zones_cannot_have_a_plan(self):
        self.group.geo_custom_zones.clear()
        self.authenticate_user(self.writer)

        response = self.client.post(
            PLAN_URL,
            {
                "userGroupUuid": str(self.group.uuid),
                "name": "Plan sans zone",
                "startDate": "2026-01-01",
                "endDate": "2026-12-31",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("userGroupUuid", response.json())


class ControlPlanEligibilityTests(ControlPlanTestCase):
    def _proposed(self, **criteria):
        plan = self.create_plan()
        response = self.create_wave(plan["uuid"], **criteria)
        self.assertEqual(response.status_code, 201, response.content)
        return set(self.proposed_parcel_ids(plan["uuid"]))

    def test_suspect_objects_not_controlled_are_proposed(self):
        eligible = self.make_parcel()
        self.make_object(eligible)
        controlled = self.make_parcel()
        self.make_object(
            controlled,
            detections=[{"control": DetectionControlStatus.CONTROLLED_FIELD}],
        )
        legal = self.make_parcel()
        self.make_object(
            legal, detections=[{"validation": DetectionValidationStatus.LEGITIMATE}]
        )

        self.assertEqual(self._proposed(), {eligible.id_parcellaire})

    def test_the_current_detection_decides_never_an_older_last_one(self):
        """A BACKGROUND tile set is not hidden by a newer PARTIAL one: both are « last ».
        The object was controlled on the newer one, so it must not be proposed — the
        plan would otherwise set it back to « À contrôler »."""
        partial = create_tile_set(
            name="Montpellier 2025 partiel",
            date=date(2025, 6, 1),
            tile_set_type=TileSetType.PARTIAL,
        )
        partial.geo_zones.add(self.montpellier)
        parcel = self.make_parcel()
        self.make_object(
            parcel,
            detections=[
                {"tile_set": self.ts_2024},
                {
                    "tile_set": partial,
                    "control": DetectionControlStatus.CONTROLLED_FIELD,
                },
            ],
        )

        self.assertEqual(self._proposed(), set())

    def test_a_deactivated_tile_set_holds_no_current_detection(self):
        deactivated = create_tile_set(
            name="Hérault 2025 désactivé",
            date=date(2025, 6, 1),
            tile_set_status=TileSetStatus.DEACTIVATED,
        )
        deactivated.geo_zones.add(self.herault)
        parcel = self.make_parcel()
        self.make_object(
            parcel,
            detections=[
                {"tile_set": self.ts_2024},
                {
                    "tile_set": deactivated,
                    "control": DetectionControlStatus.CONTROLLED_FIELD,
                },
            ],
        )

        self.assertEqual(self._proposed(), {parcel.id_parcellaire})

    def test_unverified_objects_follow_the_selected_statuses(self):
        parcel = self.make_parcel()
        self.make_object(
            parcel,
            detections=[
                {"validation": DetectionValidationStatus.DETECTED_NOT_VERIFIED}
            ],
        )

        self.assertEqual(self._proposed(), {parcel.id_parcellaire})
        ControlPlan.objects.update(deleted=True)
        self.assertEqual(self._proposed(validationStatuses=["SUSPECT"]), set())

    def test_illegal_rides_with_suspect(self):
        parcel = self.make_parcel()
        self.make_object(
            parcel, detections=[{"validation": DetectionValidationStatus.ILLEGAL}]
        )

        self.assertEqual(
            self._proposed(validationStatuses=["SUSPECT"]), {parcel.id_parcellaire}
        )

    def test_prescribed_objects_are_left_out_unless_asked(self):
        parcel = self.make_parcel()
        self.make_object(
            parcel,
            detections=[{"prescription": DetectionPrescriptionStatus.PRESCRIBED}],
        )

        self.assertEqual(self._proposed(), set())
        ControlPlan.objects.update(deleted=True)
        self.assertEqual(
            self._proposed(includePrescribed=True), {parcel.id_parcellaire}
        )

    def test_score_threshold_but_drawn_objects_bypass_it(self):
        low = self.make_parcel()
        self.make_object(low, detections=[{"score": 0.2}])
        drawn = self.make_parcel()
        self.make_object(
            drawn,
            detections=[{"score": 0.2, "source": DetectionSource.INTERFACE_DRAWN}],
        )

        self.assertEqual(self._proposed(), {drawn.id_parcellaire})

    def test_zones_selection_with_drawn_objects_outside_them(self):
        in_b = self.make_parcel()
        self.make_object(in_b, zones=("b",))
        outside = self.make_parcel()
        self.make_object(outside, zones=())
        drawn_outside = self.make_parcel()
        self.make_object(
            drawn_outside,
            zones=(),
            detections=[{"source": DetectionSource.INTERFACE_DRAWN}],
        )

        self.assertEqual(
            self._proposed(customZoneGroups=[[str(self.zone_a.uuid)]]),
            {drawn_outside.id_parcellaire},
        )

    def test_object_types(self):
        cabane = self.make_parcel()
        self.make_object(cabane, object_type=self.cabane)
        piscine = self.make_parcel()
        self.make_object(piscine, object_type=self.piscine)

        self.assertEqual(
            self._proposed(objectTypesUuids=[str(self.piscine.uuid)]),
            {piscine.id_parcellaire},
        )

    def test_parcels_with_an_official_report_or_what_follows_are_left_out(self):
        clean = self.make_parcel()
        self.make_object(clean)
        excluded = []
        for control in (
            DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
            DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
            DetectionControlStatus.JUGEMENT,
        ):
            parcel = self.make_parcel()
            self.make_object(parcel)
            # another object of the parcel, on an older year
            self.make_object(
                parcel, detections=[{"tile_set": self.ts_2021, "control": control}]
            )
            excluded.append(parcel.id_parcellaire)
        dated = self.make_parcel()
        self.make_object(dated)
        self.make_object(
            dated,
            detections=[
                {
                    "control": DetectionControlStatus.REHABILITATED,
                    "official_report_date": date(2023, 3, 1),
                }
            ],
        )
        excluded.append(dated.id_parcellaire)

        self.assertEqual(self._proposed(), {clean.id_parcellaire})
        ControlPlan.objects.update(deleted=True)
        self.assertEqual(
            self._proposed(excludeOfficialReportParcels=False),
            {clean.id_parcellaire, *excluded},
        )

    def test_parcels_with_an_urbanism_authorization_are_left_out_unless_asked(self):
        parcel = self.make_parcel()
        self.make_object(parcel)
        _, (legal,) = self.make_object(
            parcel,
            detections=[{"validation": DetectionValidationStatus.LEGITIMATE}],
        )
        DetectionAuthorization.objects.create(
            detection_data=legal.detection_data,
            authorization_date=date(2022, 1, 1),
            authorization_id="PC0341722200001",
        )

        self.assertEqual(self._proposed(), set())
        ControlPlan.objects.update(deleted=True)
        self.assertEqual(
            self._proposed(excludeAuthorizedParcels=False), {parcel.id_parcellaire}
        )

    def test_minimum_objects_count(self):
        single = self.make_parcel()
        self.make_object(single)
        double = self.make_parcel()
        self.make_object(double)
        self.make_object(double, object_type=self.piscine)

        self.assertEqual(self._proposed(minObjectsCount=2), {double.id_parcellaire})

    def test_objects_without_a_parcel_never_enter(self):
        self.make_object(None, commune=self.montpellier)

        self.assertEqual(self._proposed(), set())

    def test_perimeter(self):
        montpellier = self.make_parcel()
        self.make_object(montpellier)
        beziers = self.make_parcel(commune=self.beziers)
        self.make_object(beziers)

        self.assertEqual(
            self._proposed(communesUuids=[str(self.beziers.uuid)]),
            {beziers.id_parcellaire},
        )

    def test_a_perimeter_outside_the_territory_is_refused(self):
        plan = self.create_plan()

        response = self.create_wave(plan["uuid"], communesUuids=[str(self.nimes.uuid)])

        self.assertEqual(response.status_code, 400)
        self.assertIn("communesUuids", response.json()["criteria"])

    def test_inactive_or_foreign_zones_are_refused(self):
        plan = self.create_plan()
        foreign = GeoCustomZone.objects.create(
            name="Zone d'un autre groupe",
            geometry=self.create_bbox_polygon(2.5, 42.5, 5.0, 45.0),
        )

        response = self.create_wave(
            plan["uuid"], customZoneGroups=[[str(foreign.uuid)]]
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("customZoneGroups", response.json()["criteria"])

        self.zone_b.geo_custom_zone_status = GeoCustomZoneStatus.INACTIVE
        self.zone_b.save()
        response = self.create_wave(plan["uuid"])
        self.assertEqual(response.status_code, 400)

    def test_malformed_criteria_are_refused(self):
        plan = self.create_plan()

        response = self.create_wave(
            plan["uuid"],
            rankingCriteria=["OBJECTS_COUNT", "OBJECTS_COUNT"],
            customZoneGroups=[],
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(response.json()["criteria"]), {"rankingCriteria", "customZoneGroups"}
        )


class ControlPlanRankingTests(ControlPlanTestCase):
    def _ranked(self, **criteria):
        plan = self.create_plan()
        response = self.create_wave(plan["uuid"], **criteria)
        self.assertEqual(response.status_code, 201, response.content)
        return self.section(plan["uuid"], "PROPOSED")

    def setUp(self):
        super().setUp()
        # a: one object in the priority zone, seen since 2021
        self.parcel_a = self.make_parcel()
        self.make_object(
            self.parcel_a,
            detections=[{"tile_set": self.ts_2021}, {"tile_set": self.ts_2024}],
        )
        # b: two objects in the second zone, both new in 2024
        self.parcel_b = self.make_parcel()
        self.make_object(self.parcel_b, zones=("b",))
        self.make_object(self.parcel_b, zones=("b",), object_type=self.piscine)
        # c: three objects of the second zone, all there since 2021
        self.parcel_c = self.make_parcel()
        for _ in range(3):
            self.make_object(
                self.parcel_c,
                zones=("b",),
                detections=[{"tile_set": self.ts_2021}, {"tile_set": self.ts_2024}],
            )

    def _order(self, rows):
        return [row["idParcellaire"] for row in rows]

    def test_the_zones_filter_but_never_rank(self):
        rows = self._ranked(
            customZoneGroups=[[str(self.zone_b.uuid)], [str(self.zone_a.uuid)]]
        )

        self.assertEqual(
            self._order(rows),
            [
                self.parcel_c.id_parcellaire,
                self.parcel_b.id_parcellaire,
                self.parcel_a.id_parcellaire,
            ],
        )
        self.assertEqual([row["rank"] for row in rows], [1, 2, 3])

    def test_the_dropped_zone_priority_is_refused_but_ignored_once_stored(self):
        plan = self.create_plan()
        response = self.create_wave(
            plan["uuid"], rankingCriteria=["ZONE_PRIORITY", "OBJECTS_COUNT"]
        )
        self.assertEqual(response.status_code, 400)

        response = self.create_wave(plan["uuid"])
        self.assertEqual(response.status_code, 201, response.content)
        wave = ControlPlanWave.objects.get(uuid=response.json()["uuid"])
        wave.criteria["ranking_criteria"] = ["ZONE_PRIORITY", "OBJECTS_COUNT"]
        wave.save()

        response = self.client.post(f"{WAVE_URL}{wave.uuid}/validate/")
        self.assertEqual(response.status_code, 200, response.content)

    def test_objects_count_first(self):
        rows = self._ranked(rankingCriteria=["OBJECTS_COUNT"])

        self.assertEqual(
            self._order(rows),
            [
                self.parcel_c.id_parcellaire,
                self.parcel_b.id_parcellaire,
                self.parcel_a.id_parcellaire,
            ],
        )

    def test_new_objects_first(self):
        rows = self._ranked(rankingCriteria=["NEW_OBJECTS_COUNT"])

        self.assertEqual(self._order(rows)[0], self.parcel_b.id_parcellaire)
        self.assertEqual(rows[0]["newObjectsCount"], 2)

    def test_without_ranking_criteria_the_cadastral_order_decides(self):
        rows = self._ranked(rankingCriteria=[])

        self.assertEqual(
            self._order(rows),
            sorted(
                [
                    self.parcel_a.id_parcellaire,
                    self.parcel_b.id_parcellaire,
                    self.parcel_c.id_parcellaire,
                ]
            ),
        )

    def test_the_ranking_is_explained(self):
        rows = self._ranked()

        first = next(
            row for row in rows if row["idParcellaire"] == self.parcel_a.id_parcellaire
        )
        self.assertEqual(first["objectsCount"], 1)
        self.assertEqual(first["newObjectsCount"], 0)
        self.assertFalse(first["addedByAgent"])
        self.assertEqual(first["zoneNames"], ["Zones agricoles plan"])
        self.assertEqual(
            first["objectTypes"],
            [
                {
                    "uuid": str(self.cabane.uuid),
                    "name": self.cabane.name,
                    "color": self.cabane.color,
                    "count": 1,
                }
            ],
        )
        self.assertEqual(first["commune"]["name"], self.montpellier.name)
        self.assertIsNone(first["followUpStatus"])
        self.assertEqual(len(first["detectionObjectUuids"]), 1)


class ControlPlanAdjustmentTests(ControlPlanTestCase):
    def setUp(self):
        super().setUp()
        self.parcels = [self.make_parcel() for _ in range(3)]
        for count, parcel in enumerate(self.parcels):
            for _ in range(3 - count):
                self.make_object(parcel)
        self.plan = self.create_plan()
        response = self.create_wave(
            self.plan["uuid"], parcels_count=1, rankingCriteria=["OBJECTS_COUNT"]
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.wave = response.json()

    def test_the_proposal_and_its_waiting_list(self):
        self.assertEqual(
            self.wave["proposal"],
            {
                "proposedCount": 1,
                "waitingCount": 2,
                "addedCount": 0,
                "excludedCount": 0,
                "objectsCount": 3,
                "unverifiedObjectsCount": 0,
            },
        )
        self.assertEqual(self.wave["eligibleParcelsCount"], 3)
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"]),
            [self.parcels[0].id_parcellaire],
        )
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"], "WAITING"),
            [self.parcels[1].id_parcellaire, self.parcels[2].id_parcellaire],
        )

    def test_excluding_brings_the_next_parcel_in_and_restoring_puts_it_back(self):
        first = self.section(self.plan["uuid"], "PROPOSED")[0]

        response = self.client.post(f"{PARCEL_URL}{first['uuid']}/exclude/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"]),
            [self.parcels[1].id_parcellaire],
        )
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"], "EXCLUDED"),
            [self.parcels[0].id_parcellaire],
        )

        response = self.client.post(f"{PARCEL_URL}{first['uuid']}/restore/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"]),
            [self.parcels[0].id_parcellaire],
        )

    def test_a_recomputation_keeps_the_exclusions(self):
        first = self.section(self.plan["uuid"], "PROPOSED")[0]
        self.client.post(f"{PARCEL_URL}{first['uuid']}/exclude/")

        response = self.client.patch(
            f"{WAVE_URL}{self.wave['uuid']}/",
            {"parcelsCount": 5, "criteria": self.criteria(rankingCriteria=[])},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["parcelsCount"], 5)
        self.assertEqual(
            set(self.proposed_parcel_ids(self.plan["uuid"])),
            {self.parcels[1].id_parcellaire, self.parcels[2].id_parcellaire},
        )
        self.assertEqual(response.json()["proposal"]["excludedCount"], 1)

    def test_restoring_after_a_recomputation_takes_the_new_rank(self):
        first = self.section(self.plan["uuid"], "PROPOSED")[0]
        self.client.post(f"{PARCEL_URL}{first['uuid']}/exclude/")
        response = self.client.patch(
            f"{WAVE_URL}{self.wave['uuid']}/",
            {"parcelsCount": 1, "criteria": self.criteria(rankingCriteria=[])},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

        self.client.post(f"{PARCEL_URL}{first['uuid']}/restore/")

        # the cadastral order now: the restored parcel first, no rank shared
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"]),
            [self.parcels[0].id_parcellaire],
        )
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"], "WAITING"),
            [self.parcels[1].id_parcellaire, self.parcels[2].id_parcellaire],
        )
        ranks = list(
            ControlPlanParcel.objects.filter(
                control_plan__uuid=self.plan["uuid"]
            ).values_list("rank", flat=True)
        )
        self.assertEqual(len(ranks), len(set(ranks)))

        response = self.client.post(f"{WAVE_URL}{self.wave['uuid']}/validate/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"], "PLANNED"),
            [self.parcels[0].id_parcellaire],
        )

    def test_one_draft_at_a_time(self):
        response = self.create_wave(self.plan["uuid"])

        self.assertEqual(response.status_code, 409)

    def test_dropping_the_draft_keeps_its_exclusions(self):
        first = self.section(self.plan["uuid"], "PROPOSED")[0]
        self.client.post(f"{PARCEL_URL}{first['uuid']}/exclude/")

        response = self.client.delete(f"{WAVE_URL}{self.wave['uuid']}/")

        self.assertEqual(response.status_code, 204)
        self.assertIsNone(
            self.client.get(f"{PLAN_URL}{self.plan['uuid']}/").json()["draftWave"]
        )
        response = self.create_wave(self.plan["uuid"])
        self.assertEqual(response.status_code, 201)
        self.assertNotIn(
            self.parcels[0].id_parcellaire, self.proposed_parcel_ids(self.plan["uuid"])
        )

    def test_a_reader_cannot_exclude(self):
        first = self.section(self.plan["uuid"], "PROPOSED")[0]
        self.authenticate_user(self.reader)

        response = self.client.post(f"{PARCEL_URL}{first['uuid']}/exclude/")

        self.assertEqual(response.status_code, 403)

    def _include_last(self):
        last = self.section(self.plan["uuid"], "WAITING")[-1]
        response = self.client.post(f"{PARCEL_URL}{last['uuid']}/include/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["addedByAgent"])
        return last

    def _proposal(self):
        return self.client.get(f"{WAVE_URL}{self.wave['uuid']}/").json()["proposal"]

    def test_a_waiting_parcel_is_added_on_top_of_the_count(self):
        self._include_last()

        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"]),
            [self.parcels[0].id_parcellaire, self.parcels[2].id_parcellaire],
        )
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"], "WAITING"),
            [self.parcels[1].id_parcellaire],
        )
        proposal = self._proposal()
        self.assertEqual(
            (
                proposal["proposedCount"],
                proposal["waitingCount"],
                proposal["addedCount"],
            ),
            (2, 1, 1),
        )

        # an exclusion still brings the next waiting parcel in, the addition stays
        first = self.section(self.plan["uuid"], "PROPOSED")[0]
        self.client.post(f"{PARCEL_URL}{first['uuid']}/exclude/")
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"]),
            [self.parcels[1].id_parcellaire, self.parcels[2].id_parcellaire],
        )

    def test_an_added_parcel_is_put_back_at_its_rank(self):
        last = self._include_last()

        response = self.client.post(f"{PARCEL_URL}{last['uuid']}/put-back/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["addedByAgent"])
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"], "WAITING"),
            [self.parcels[1].id_parcellaire, self.parcels[2].id_parcellaire],
        )

    def test_an_excluded_addition_is_restored_to_the_waiting_list(self):
        last = self._include_last()
        self.client.post(f"{PARCEL_URL}{last['uuid']}/exclude/")

        response = self.client.post(f"{PARCEL_URL}{last['uuid']}/restore/")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"]),
            [self.parcels[0].id_parcellaire],
        )

    def test_only_a_waiting_parcel_is_added_and_only_an_addition_put_back(self):
        first = self.section(self.plan["uuid"], "PROPOSED")[0]
        waiting = self.section(self.plan["uuid"], "WAITING")[0]

        self.assertEqual(
            self.client.post(f"{PARCEL_URL}{first['uuid']}/include/").status_code, 409
        )
        self.assertEqual(
            self.client.post(f"{PARCEL_URL}{waiting['uuid']}/put-back/").status_code,
            409,
        )

    def test_a_reader_cannot_add(self):
        waiting = self.section(self.plan["uuid"], "WAITING")[0]
        self.authenticate_user(self.reader)

        response = self.client.post(f"{PARCEL_URL}{waiting['uuid']}/include/")

        self.assertEqual(response.status_code, 403)

    def test_a_recomputation_keeps_the_additions(self):
        self._include_last()

        response = self.client.patch(
            f"{WAVE_URL}{self.wave['uuid']}/",
            {
                "parcelsCount": 1,
                "criteria": self.criteria(rankingCriteria=["OBJECTS_COUNT"]),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"]),
            [self.parcels[0].id_parcellaire, self.parcels[2].id_parcellaire],
        )

    def test_validation_plans_the_additions(self):
        self._include_last()

        response = self.client.post(f"{WAVE_URL}{self.wave['uuid']}/validate/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["plannedParcelsCount"], 2)
        self.assertEqual(
            self.proposed_parcel_ids(self.plan["uuid"], "PLANNED"),
            [self.parcels[0].id_parcellaire, self.parcels[2].id_parcellaire],
        )


class ControlPlanEligibleCountTests(ControlPlanTestCase):
    def setUp(self):
        super().setUp()
        # objects: 3, 2, 1 and 1
        self.parcels = [self.make_parcel() for _ in range(4)]
        for parcel, objects_count in zip(self.parcels, (3, 2, 1, 1)):
            for _ in range(objects_count):
                self.make_object(parcel)
        controlled = self.make_parcel()
        self.make_object(
            controlled,
            detections=[{"control": DetectionControlStatus.CONTROLLED_FIELD}],
        )
        self.plan = self.create_plan()

    def count(self, plan_uuid=None, **criteria):
        return self.client.post(
            f"{PLAN_URL}{plan_uuid or self.plan['uuid']}/eligible-count/",
            {"criteria": self.criteria(**criteria)},
            format="json",
        )

    def test_the_count_is_what_a_wave_would_find(self):
        for criteria, expected in (
            ({}, {"eligibleParcelsCount": 4, "eligibleObjectsCount": 7}),
            (
                {"minObjectsCount": 2},
                {"eligibleParcelsCount": 2, "eligibleObjectsCount": 5},
            ),
        ):
            response = self.count(**criteria)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json(), expected)

        # nothing stored
        self.assertFalse(ControlPlanWave.objects.exists())
        self.assertFalse(ControlPlanParcel.objects.exists())

        wave = self.create_wave(self.plan["uuid"], parcels_count=1, minObjectsCount=2)
        self.assertEqual(wave.status_code, 201, wave.content)
        self.assertEqual(wave.json()["eligibleParcelsCount"], 2)

    def test_the_proposed_parcels_of_the_draft_still_count(self):
        wave = self.create_wave(self.plan["uuid"], parcels_count=1).json()

        response = self.count()

        self.assertEqual(
            response.json()["eligibleParcelsCount"], wave["eligibleParcelsCount"]
        )
        self.assertEqual(response.json()["eligibleParcelsCount"], 4)

    def test_planned_and_excluded_parcels_are_not_counted(self):
        first = self.create_wave(
            self.plan["uuid"], parcels_count=1, rankingCriteria=["OBJECTS_COUNT"]
        ).json()
        self.client.post(f"{WAVE_URL}{first['uuid']}/validate/")
        # still eligible on its own, but its parcel is in the plan
        self.make_object(self.parcels[0])
        second = self.create_wave(
            self.plan["uuid"], parcels_count=1, rankingCriteria=["OBJECTS_COUNT"]
        ).json()
        proposed = self.section(self.plan["uuid"], "PROPOSED")[0]
        self.assertEqual(proposed["idParcellaire"], self.parcels[1].id_parcellaire)
        self.client.post(f"{PARCEL_URL}{proposed['uuid']}/exclude/")

        response = self.count(rankingCriteria=["OBJECTS_COUNT"])

        self.assertEqual(
            response.json(), {"eligibleParcelsCount": 2, "eligibleObjectsCount": 2}
        )
        recomputed = self.client.patch(
            f"{WAVE_URL}{second['uuid']}/",
            {"criteria": self.criteria(rankingCriteria=["OBJECTS_COUNT"])},
            format="json",
        )
        self.assertEqual(recomputed.json()["eligibleParcelsCount"], 2)

    def test_invalid_criteria_are_refused(self):
        response = self.count(
            rankingCriteria=["OBJECTS_COUNT", "OBJECTS_COUNT"], customZoneGroups=[]
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(response.json()["criteria"]), {"rankingCriteria", "customZoneGroups"}
        )

        response = self.count(communesUuids=[str(self.nimes.uuid)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("communesUuids", response.json()["criteria"])

        response = self.client.post(
            f"{PLAN_URL}{self.plan['uuid']}/eligible-count/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("criteria", response.json())

    def test_a_reader_is_refused(self):
        self.authenticate_user(self.reader)

        self.assertEqual(self.count().status_code, 403)

    def test_the_plan_of_another_group_is_not_found(self):
        stranger = create_regular_user(email="plan-count-stranger@test.com")
        other_group = create_user_group(name="Gard plan", geo_zones=[self.nimes])
        other_group.feature_flags = [FeatureFlag.PLAN_DE_CONTROLE]
        other_group.save()
        add_user_to_group(stranger, other_group)
        self.authenticate_user(stranger)

        self.assertEqual(self.count().status_code, 404)

    def test_a_closed_plan_conflicts(self):
        self.client.post(f"{PLAN_URL}{self.plan['uuid']}/close/")

        self.assertEqual(self.count().status_code, 409)

    def test_a_timeout_is_a_503(self):
        with mock.patch(
            "core.services.control_plan._collect_candidates",
            side_effect=OperationalError(
                "canceling statement due to statement timeout"
            ),
        ):
            response = self.count()

        self.assertEqual(response.status_code, 503)

    def test_a_super_admin_count_is_not_logged(self):
        super_admin = create_user(
            email="plan-count-super@test.com", user_role=UserRole.SUPER_ADMIN
        )
        self.authenticate_user(super_admin)
        scope = {HEADER_NAME: str(self.group.uuid)}

        response = self.client.post(
            f"{PLAN_URL}{self.plan['uuid']}/eligible-count/",
            {"criteria": self.criteria()},
            format="json",
            **scope,
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["eligibleParcelsCount"], 4)
        self.assertFalse(UserActionLog.objects.exists())
        # the plan writes still are
        self.client.post(f"{PLAN_URL}{self.plan['uuid']}/close/", **scope)
        self.assertEqual(
            list(UserActionLog.objects.values_list("route", flat=True)),
            [f"{PLAN_URL}{self.plan['uuid']}/close/"],
        )


class ControlPlanValidationTests(ControlPlanTestCase):
    def test_validation_sets_the_current_detections_to_control(self):
        parcel = self.make_parcel()
        detection_object, (old, current) = self.make_object(
            parcel,
            detections=[
                {"tile_set": self.ts_2021},
                {
                    "tile_set": self.ts_2024,
                    "validation": DetectionValidationStatus.DETECTED_NOT_VERIFIED,
                },
            ],
        )
        waiting = self.make_parcel()
        self.make_object(waiting, zones=("b",))
        before = current.detection_data.updated_at

        with mock.patch(
            "core.services.control_plan.invalidate_count_caches"
        ) as invalidate, self.captureOnCommitCallbacks(execute=True):
            # same counts: the cadastral order puts `parcel` first
            plan, result = self.plan_and_validate(
                parcels_count=1, rankingCriteria=["OBJECTS_COUNT"]
            )

        self.assertEqual(
            result,
            {"plannedParcelsCount": 1, "switchedObjectsCount": 1, "skippedParcels": []},
        )
        invalidate.assert_called()

        current_data = DetectionData.objects.get(id=current.detection_data_id)
        self.assertEqual(
            current_data.detection_control_status, DetectionControlStatus.TO_CONTROL
        )
        self.assertEqual(
            current_data.detection_validation_status, DetectionValidationStatus.SUSPECT
        )
        self.assertEqual(current_data.user_last_update, self.writer)
        self.assertGreater(current_data.updated_at, before)
        history = current_data.history.order_by("-history_date", "-history_id").first()
        self.assertEqual(
            history.history_change_reason, CONTROL_PLAN_HISTORY_CHANGE_REASON
        )
        self.assertEqual(history.history_user, self.writer)

        old_data = DetectionData.objects.get(id=old.detection_data_id)
        self.assertEqual(
            old_data.detection_control_status, DetectionControlStatus.NOT_CONTROLLED
        )

        planned = ControlPlanParcel.objects.get(control_plan__uuid=plan["uuid"])
        self.assertEqual(planned.parcel, parcel)
        self.assertEqual(
            list(
                planned.control_plan_parcel_objects.values_list(
                    "detection_object_id", "previous_validation_status"
                )
            ),
            [(detection_object.id, DetectionValidationStatus.DETECTED_NOT_VERIFIED)],
        )
        # the waiting list is dropped: a next wave may propose it
        self.assertFalse(ControlPlanParcel.objects.filter(parcel=waiting).exists())

        response = self.client.get(f"{PLAN_URL}{plan['uuid']}/")
        self.assertIsNone(response.json()["draftWave"])
        self.assertEqual(response.json()["validatedWavesCount"], 1)
        last_wave = response.json()["lastValidatedWave"]
        self.assertEqual(last_wave["controlPlanWaveStatus"], "VALIDATED")
        self.assertEqual(last_wave["parcelsCount"], 1)
        self.assertEqual(
            last_wave["criteria"]["customZoneGroups"],
            [[str(self.zone_a.uuid)], [str(self.zone_b.uuid)]],
        )

    def test_an_object_controlled_meanwhile_is_skipped_and_never_downgraded(self):
        parcel = self.make_parcel()
        _, (detection,) = self.make_object(parcel)
        self.make_object(self.make_parcel())
        plan = self.create_plan()
        wave = self.create_wave(plan["uuid"]).json()

        detection.detection_data.detection_control_status = (
            DetectionControlStatus.CONTROLLED_FIELD
        )
        detection.detection_data.save()

        response = self.client.post(f"{WAVE_URL}{wave['uuid']}/validate/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["plannedParcelsCount"], 1)
        self.assertEqual(
            response.json()["skippedParcels"],
            [
                {
                    "idParcellaire": parcel.id_parcellaire,
                    "communeName": self.montpellier.name,
                }
            ],
        )
        detection.detection_data.refresh_from_db()
        self.assertEqual(
            detection.detection_data.detection_control_status,
            DetectionControlStatus.CONTROLLED_FIELD,
        )

    def test_a_validation_planning_nothing_conflicts(self):
        parcel = self.make_parcel()
        _, (detection,) = self.make_object(parcel)
        plan = self.create_plan()
        wave = self.create_wave(plan["uuid"]).json()
        detection.detection_data.detection_control_status = (
            DetectionControlStatus.CONTROLLED_FIELD
        )
        detection.detection_data.save()

        response = self.client.post(f"{WAVE_URL}{wave['uuid']}/validate/")

        self.assertEqual(response.status_code, 409)
        # the draft stays, and the plan can still be deleted
        self.assertEqual(
            ControlPlanWave.objects.get(uuid=wave["uuid"]).control_plan_wave_status,
            "DRAFT",
        )
        self.assertEqual(
            self.client.delete(f"{PLAN_URL}{plan['uuid']}/").status_code, 204
        )

    def test_objects_the_caller_cannot_edit_are_left_out(self):
        locked_parcel = self.make_parcel()
        _, (locked,) = self.make_object(locked_parcel)
        _, (editable,) = self.make_object(self.make_parcel())
        plan = self.create_plan()
        wave = self.create_wave(plan["uuid"]).json()

        with mock.patch.object(
            DetectionPermission,
            "writable_detections",
            lambda _, detections: detections.exclude(id=locked.id),
        ):
            response = self.client.post(f"{WAVE_URL}{wave['uuid']}/validate/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["plannedParcelsCount"], 1)
        self.assertEqual(
            [row["idParcellaire"] for row in response.json()["skippedParcels"]],
            [locked_parcel.id_parcellaire],
        )
        for detection, control in (
            (locked, DetectionControlStatus.NOT_CONTROLLED),
            (editable, DetectionControlStatus.TO_CONTROL),
        ):
            detection.detection_data.refresh_from_db()
            self.assertEqual(detection.detection_data.detection_control_status, control)

    def test_a_wave_is_validated_once(self):
        parcel = self.make_parcel()
        self.make_object(parcel)
        plan = self.create_plan()
        wave = self.create_wave(plan["uuid"]).json()

        self.assertEqual(
            self.client.post(f"{WAVE_URL}{wave['uuid']}/validate/").status_code, 200
        )
        self.assertEqual(
            self.client.post(f"{WAVE_URL}{wave['uuid']}/validate/").status_code, 409
        )

    def test_a_next_wave_skips_the_planned_parcels(self):
        planned = self.make_parcel()
        self.make_object(planned)
        plan, _ = self.plan_and_validate()
        later = self.make_parcel()
        self.make_object(later)

        response = self.create_wave(plan["uuid"])

        self.assertEqual(response.json()["number"], 2)
        self.assertEqual(self.proposed_parcel_ids(plan["uuid"]), [later.id_parcellaire])


class ControlPlanFollowUpTests(ControlPlanTestCase):
    def setUp(self):
        super().setUp()
        self.parcel = self.make_parcel()
        _, (self.detection,) = self.make_object(
            self.parcel,
            detections=[
                {"validation": DetectionValidationStatus.DETECTED_NOT_VERIFIED}
            ],
        )
        self.plan, _ = self.plan_and_validate()

    def _set_control(self, control):
        data = self.detection.detection_data
        data.refresh_from_db()
        data.detection_control_status = control
        data.save()

    def _counters(self):
        return self.client.get(f"{PLAN_URL}{self.plan['uuid']}/").json()["counters"]

    def test_follow_up_states(self):
        self.assertEqual(
            self._counters(),
            {
                "planned": 1,
                "toControl": 1,
                "controlled": 0,
                "released": 0,
                "removed": 0,
                "excluded": 0,
            },
        )
        self.assertEqual(
            self.section(self.plan["uuid"], "PLANNED")[0]["followUpStatus"],
            "TO_CONTROL",
        )

        self._set_control(DetectionControlStatus.CONTROLLED_FIELD)
        self.assertEqual(self._counters()["controlled"], 1)
        self.assertEqual(
            len(
                self.section(self.plan["uuid"], "PLANNED", followUpStatus="CONTROLLED")
            ),
            1,
        )
        self.assertEqual(
            self.section(self.plan["uuid"], "PLANNED", followUpStatus="TO_CONTROL"), []
        )

        self._set_control(DetectionControlStatus.NOT_CONTROLLED)
        self.assertEqual(self._counters()["released"], 1)

    def test_removal_undoes_what_the_plan_did(self):
        row = self.section(self.plan["uuid"], "PLANNED")[0]

        response = self.client.post(f"{PARCEL_URL}{row['uuid']}/remove/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["controlPlanParcelStatus"], "REMOVED")
        data = DetectionData.objects.get(id=self.detection.detection_data_id)
        self.assertEqual(
            data.detection_control_status, DetectionControlStatus.NOT_CONTROLLED
        )
        self.assertEqual(
            data.detection_validation_status,
            DetectionValidationStatus.DETECTED_NOT_VERIFIED,
        )
        self.assertEqual(
            data.history.order_by("-history_date", "-history_id")
            .first()
            .history_change_reason,
            CONTROL_PLAN_HISTORY_CHANGE_REASON,
        )
        self.assertEqual(self._counters()["removed"], 1)

    def test_removal_leaves_a_controlled_object_alone(self):
        self._set_control(DetectionControlStatus.CONTROLLED_FIELD)
        row = self.section(self.plan["uuid"], "PLANNED")[0]

        self.client.post(f"{PARCEL_URL}{row['uuid']}/remove/")

        data = DetectionData.objects.get(id=self.detection.detection_data_id)
        self.assertEqual(
            data.detection_control_status, DetectionControlStatus.CONTROLLED_FIELD
        )

    def test_a_closed_plan_keeps_its_parcels(self):
        row = self.section(self.plan["uuid"], "PLANNED")[0]
        self.client.post(f"{PLAN_URL}{self.plan['uuid']}/close/")

        response = self.client.post(f"{PARCEL_URL}{row['uuid']}/remove/")

        self.assertEqual(response.status_code, 409)
        data = DetectionData.objects.get(id=self.detection.detection_data_id)
        self.assertEqual(
            data.detection_control_status, DetectionControlStatus.TO_CONTROL
        )

    def test_out_of_plan_lists_the_objects_set_to_control_by_hand(self):
        by_hand = self.make_parcel()
        detection_object, _ = self.make_object(
            by_hand, detections=[{"control": DetectionControlStatus.TO_CONTROL}]
        )

        response = self.client.get(f"{PLAN_URL}{self.plan['uuid']}/out-of-plan/")

        self.assertEqual(response.status_code, 200)
        rows = response.json()["results"]
        self.assertEqual(
            [row["idParcellaire"] for row in rows], [by_hand.id_parcellaire]
        )
        self.assertEqual(rows[0]["detectionObjectUuids"], [str(detection_object.uuid)])

    def test_preview(self):
        # previews match the tile sets by zone geometry, and the Hérault of the fixtures
        # stops west of Montpellier
        self.ts_2024.geo_zones.add(self.montpellier)
        row = self.section(self.plan["uuid"], "PLANNED")[0]

        response = self.client.get(f"{PARCEL_URL}{row['uuid']}/preview/")

        self.assertEqual(response.status_code, 200)
        preview = response.json()
        self.assertEqual(preview["parcelGeometry"]["type"], "Polygon")
        self.assertEqual(len(preview["bounds"]), 4)
        self.assertEqual(
            [obj["detectionControlStatus"] for obj in preview["detectionObjects"]],
            ["TO_CONTROL"],
        )
        self.assertTrue(preview["tileSetPreviews"])

    def test_each_preview_year_shows_its_own_detections(self):
        self.ts_2021.geo_zones.add(self.montpellier)
        self.ts_2024.geo_zones.add(self.montpellier)
        parcel = self.make_parcel()
        x, y = parcel.geometry.centroid.coords
        self.make_object(
            parcel,
            detections=[
                {"tile_set": self.ts_2021, "geometry": Point(x, y, srid=SRID)},
                {"tile_set": self.ts_2024, "geometry": Point(x + 0.0001, y, srid=SRID)},
            ],
        )
        # a second wave of the plan proposes it
        wave = self.create_wave(self.plan["uuid"])
        self.assertEqual(wave.status_code, 201, wave.content)
        row = self.section(self.plan["uuid"], "PROPOSED")[0]

        preview = self.client.get(f"{PARCEL_URL}{row['uuid']}/preview/").json()

        by_year = {
            tile_set_preview["tileSet"]["name"]: [
                obj["geometry"]["coordinates"]
                for obj in tile_set_preview["detectionObjects"]
            ]
            for tile_set_preview in preview["tileSetPreviews"]
        }
        ((x_2021, _),) = by_year[self.ts_2021.name]
        ((x_2024, _),) = by_year[self.ts_2024.name]
        self.assertAlmostEqual(x_2021, x)
        self.assertAlmostEqual(x_2024, x + 0.0001)

    def test_a_deleted_parcel_keeps_its_line_in_the_plan(self):
        self.parcel.delete()

        rows = self.section(self.plan["uuid"], "PLANNED")

        self.assertIsNone(rows[0]["parcelUuid"])
        self.assertEqual(rows[0]["idParcellaire"], self.parcel.id_parcellaire)

    def test_closing_keeps_the_statuses(self):
        self.client.post(f"{PLAN_URL}{self.plan['uuid']}/close/")

        data = DetectionData.objects.get(id=self.detection.detection_data_id)
        self.assertEqual(
            data.detection_control_status, DetectionControlStatus.TO_CONTROL
        )


class ControlPlanOptionsTests(ControlPlanTestCase):
    def test_criteria_options(self):
        plan = self.create_plan()

        response = self.client.get(f"{PLAN_URL}{plan['uuid']}/criteria-options/")

        self.assertEqual(response.status_code, 200)
        options = response.json()
        self.assertEqual(
            {object_type["name"] for object_type in options["objectTypes"]},
            {self.cabane.name, self.piscine.name},
        )
        self.assertEqual(
            [
                (group["name"], group["customZoneUuids"])
                for group in options["customZoneGroups"]
            ],
            [
                ("Zone naturelle plan", [str(self.zone_b.uuid)]),
                ("Zones agricoles plan", [str(self.zone_a.uuid)]),
            ],
        )

    def _join_a_group_with_boats(self):
        bateau, category = create_object_type_with_category(
            object_type_name="Bateau plan", category_name="Littoral plan"
        )
        other_group = create_user_group(name="DDTM 30 plan", geo_zones=[self.herault])
        other_group.object_type_categories.add(category)
        add_user_to_group(self.writer, other_group)
        return bateau

    def test_object_types_are_those_of_the_plan_group(self):
        bateau = self._join_a_group_with_boats()
        plan = self.create_plan()

        options = self.client.get(f"{PLAN_URL}{plan['uuid']}/criteria-options/")
        self.assertNotIn(
            bateau.name,
            {object_type["name"] for object_type in options.json()["objectTypes"]},
        )

        response = self.create_wave(plan["uuid"], objectTypesUuids=[str(bateau.uuid)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("objectTypesUuids", response.json()["criteria"])

    def test_a_group_without_categories_offers_the_caller_types(self):
        bateau = self._join_a_group_with_boats()
        self.group.object_type_categories.clear()
        plan = self.create_plan()

        options = self.client.get(f"{PLAN_URL}{plan['uuid']}/criteria-options/")

        self.assertEqual(
            [object_type["name"] for object_type in options.json()["objectTypes"]],
            [bateau.name],
        )

    def test_criteria_options_default_perimeter(self):
        plan = self.create_plan()

        response = self.client.get(f"{PLAN_URL}{plan['uuid']}/criteria-options/")

        # a group holding a department starts on its whole territory
        self.assertEqual(
            response.json()["defaultPerimeter"], {"communes": [], "epcis": []}
        )
        self.assertIsNone(response.json()["singleCommune"])

    def test_the_single_commune_of_a_group(self):
        commune_group = create_user_group(
            name="Commune plan", geo_zones=[self.montpellier]
        )
        communes_group = create_user_group(
            name="Communes plan", geo_zones=[self.montpellier, self.beziers]
        )

        self.assertEqual(
            ControlPlanService.single_commune(commune_group),
            {
                "uuid": self.montpellier.uuid,
                "name": self.montpellier.name,
                "code": self.montpellier.iso_code,
            },
        )
        self.assertIsNone(ControlPlanService.single_commune(communes_group))

    def test_default_perimeter_of_a_collectivity(self):
        epci = create_montpellier_mediterranee_epci(department=self.herault)
        communes_group = create_user_group(
            name="Communes plan", geo_zones=[self.montpellier, self.beziers]
        )
        epci_group = create_user_group(name="EPCI plan", geo_zones=[epci])
        for group in (communes_group, epci_group):
            group.user_group_type = UserGroupType.COLLECTIVITY
            group.save()

        self.assertEqual(
            ControlPlanService.default_perimeter(communes_group),
            {
                "communes": [
                    {
                        "uuid": commune.uuid,
                        "name": commune.name,
                        "code": commune.iso_code,
                    }
                    for commune in sorted(
                        [self.montpellier, self.beziers], key=lambda c: c.name
                    )
                ],
                "epcis": [],
            },
        )
        self.assertEqual(
            ControlPlanService.default_perimeter(epci_group),
            {
                "communes": [],
                "epcis": [
                    {"uuid": epci.uuid, "name": epci.name, "code": epci.siren_code}
                ],
            },
        )

    def test_no_default_perimeter_for_a_ddtm_or_a_department(self):
        ddtm = create_user_group(
            name="DDTM communes plan", geo_zones=[self.montpellier]
        )
        ddtm.user_group_type = UserGroupType.DDTM
        ddtm.save()
        department = create_user_group(
            name="Département plan", geo_zones=[self.herault, self.montpellier]
        )
        department.user_group_type = UserGroupType.COLLECTIVITY
        department.save()

        for group in (ddtm, department):
            self.assertEqual(
                ControlPlanService.default_perimeter(group),
                {"communes": [], "epcis": []},
            )

    def test_prerequisites(self):
        unverified = self.make_parcel()
        self.make_object(
            unverified,
            detections=[
                {"validation": DetectionValidationStatus.DETECTED_NOT_VERIFIED}
            ],
        )
        self.make_object(None, commune=self.montpellier)
        self.authenticate_user(self.writer)

        response = self.client.get(
            f"{PLAN_URL}prerequisites/", {"userGroupUuid": str(self.group.uuid)}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "customZonesCount": 2,
                "unverifiedObjectsCount": 1,
                "objectsWithoutParcelCount": 1,
            },
        )

    def test_prerequisites_of_a_group_without_active_zones(self):
        self.zone_a.geo_custom_zone_status = GeoCustomZoneStatus.INACTIVE
        self.zone_a.save()
        self.group.geo_custom_zones.remove(self.zone_b)
        self.authenticate_user(self.writer)

        response = self.client.get(
            f"{PLAN_URL}prerequisites/", {"userGroupUuid": str(self.group.uuid)}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["customZonesCount"], 0)

    def test_the_flag_is_offered_to_the_user_groups(self):
        self.assertIn(
            (FeatureFlag.PLAN_DE_CONTROLE, "Plan de contrôle"), FeatureFlag.choices
        )


class ControlPlanSideEffectsTests(ControlPlanTestCase):
    def test_activity_statistics_ignore_the_plan_switches(self):
        parcel = self.make_parcel()
        _, (detection,) = self.make_object(parcel)
        since = timezone.now() - timedelta(days=1)
        self.plan_and_validate()

        data = DetectionData.objects.get(id=detection.detection_data_id)
        data.set_detection_control_status(DetectionControlStatus.CONTROLLED_FIELD)
        data._history_user = self.writer
        data.save()

        transitions = DdtmActivityService._control_status_transitions(
            [self.writer.id], since
        )

        self.assertEqual(
            [status for _, _, status, _ in transitions],
            [DetectionControlStatus.CONTROLLED_FIELD],
        )

    def test_cleaning_detections_drops_their_plan_objects(self):
        cleaned_tile_set = create_tile_set(
            name="Hérault 2024 bis", date=date(2024, 7, 1)
        )
        cleaned_tile_set.geo_zones.add(self.herault)
        parcel = self.make_parcel()
        detection_object, _ = self.make_object(
            parcel, detections=[{"tile_set": cleaned_tile_set}]
        )
        self.plan_and_validate()
        self.assertTrue(
            ControlPlanParcelObject.objects.filter(
                detection_object=detection_object
            ).exists()
        )

        call_command("clean_detections", tile_set_id=cleaned_tile_set.id)
        # deferred foreign keys are checked at commit, which a test never reaches
        connection.check_constraints()

        self.assertFalse(
            ControlPlanParcelObject.objects.filter(
                detection_object_id=detection_object.id
            ).exists()
        )
