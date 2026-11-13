"""`controlPlan=true` on the map, the detection list and the parcel table: the parcels of
the plan, plus the objects set « À contrôler » outside it."""

from core.models.detection import DetectionSource
from core.models.detection_data import DetectionControlStatus
from core.tests.fixtures.control_plan import PLAN_URL, ControlPlanTestCase
from core.tests.fixtures.users import (
    add_user_to_group,
    create_regular_user,
    create_user_group,
)


class ControlPlanFilterTests(ControlPlanTestCase):
    def setUp(self):
        super().setUp()
        self.planned_parcel = self.make_parcel()
        _, (self.planned,) = self.make_object(self.planned_parcel)
        # same parcel, a type the plan left out: still shown, the whole parcel is planned
        _, (self.planned_neighbour,) = self.make_object(
            self.planned_parcel, object_type=self.piscine
        )
        self.plan, _ = self.plan_and_validate(objectTypesUuids=[str(self.cabane.uuid)])

        self.by_hand_parcel = self.make_parcel()
        _, (self.by_hand,) = self.make_object(
            self.by_hand_parcel,
            detections=[{"control": DetectionControlStatus.TO_CONTROL}],
        )
        _, (self.by_hand_neighbour,) = self.make_object(self.by_hand_parcel)
        _, (self.unrelated,) = self.make_object(self.make_parcel())

        self.params = {
            "customZonesUuids": f"{self.zone_a.uuid},{self.zone_b.uuid}",
            "objectTypesUuids": f"{self.cabane.uuid},{self.piscine.uuid}",
            "interfaceDrawn": "ALL",
        }

    @staticmethod
    def _rows(response):
        return (
            response.data["results"]
            if isinstance(response.data, dict)
            else response.data
        )

    def _detection_uuids(self, url, **params):
        response = self.client.get(url, {**self.params, **params})
        self.assertEqual(response.status_code, 200, response.content)
        return {str(row["uuid"]) for row in self._rows(response)}

    def _uuids(self, *detections):
        return {str(detection.uuid) for detection in detections}

    def test_the_detection_list_keeps_the_plan_and_the_objects_to_control(self):
        self.authenticate_user(self.writer)

        self.assertEqual(
            self._detection_uuids("/api/detection-list/", controlPlan="true"),
            self._uuids(self.planned, self.planned_neighbour, self.by_hand),
        )
        self.assertEqual(
            self._detection_uuids("/api/detection-list/"),
            self._uuids(
                self.planned,
                self.planned_neighbour,
                self.by_hand,
                self.by_hand_neighbour,
                self.unrelated,
            ),
        )

    def test_the_map_too(self):
        # the map also clips to the zones' geometry, and the Hérault of the fixtures
        # stops west of Montpellier
        self.group.geo_zones.add(self.montpellier)
        self.authenticate_user(self.writer)

        self.assertEqual(
            self._detection_uuids("/api/detection/", controlPlan="true"),
            self._uuids(self.planned, self.planned_neighbour, self.by_hand),
        )

    def test_the_parcel_table_too(self):
        self.authenticate_user(self.writer)

        response = self.client.get(
            "/api/parcel/list_items/", {**self.params, "controlPlan": "true"}
        )

        self.assertEqual(response.status_code, 200, response.content)
        counts = {
            row["id_parcellaire"]: row["detections_count"]
            for row in self._rows(response)
        }
        # outside the plan, only the object to control counts
        self.assertEqual(
            counts,
            {
                self.planned_parcel.id_parcellaire: 2,
                self.by_hand_parcel.id_parcellaire: 1,
            },
        )

        response = self.client.get(
            "/api/parcel/overview/", {**self.params, "controlPlan": "true"}
        )
        self.assertEqual(response.data["total"], 2)

    def test_the_objects_outside_the_zones_are_left_out(self):
        # drawn by an agent: the map's own zone filter (« ALL ») would keep them
        _, (drawn_planned,) = self.make_object(
            self.planned_parcel,
            zones=(),
            detections=[{"source": DetectionSource.INTERFACE_DRAWN}],
        )
        _, (drawn_to_control,) = self.make_object(
            self.make_parcel(),
            zones=(),
            detections=[
                {
                    "source": DetectionSource.INTERFACE_DRAWN,
                    "control": DetectionControlStatus.TO_CONTROL,
                }
            ],
        )
        self.authenticate_user(self.writer)

        everything = self._detection_uuids("/api/detection-list/")
        self.assertLessEqual(self._uuids(drawn_planned, drawn_to_control), everything)
        self.assertEqual(
            self._detection_uuids("/api/detection-list/", controlPlan="true"),
            self._uuids(self.planned, self.planned_neighbour, self.by_hand),
        )

    def test_a_closed_plan_no_longer_counts(self):
        self.authenticate_user(self.writer)
        self.client.post(f"{PLAN_URL}{self.plan['uuid']}/close/")

        self.assertEqual(
            self._detection_uuids("/api/detection-list/", controlPlan="true"),
            # still « À contrôler », but no longer a plan parcel
            self._uuids(self.planned, self.by_hand),
        )

    def test_ignored_without_access_to_the_control_plans(self):
        outsider = create_regular_user(email="filter-outsider@test.com")
        group = create_user_group(name="Hérault sans flag", geo_zones=[self.herault])
        group.object_type_categories.add(self.category)
        group.geo_custom_zones.add(self.zone_a, self.zone_b)
        add_user_to_group(outsider, group)
        self.authenticate_user(outsider)

        self.assertEqual(
            self._detection_uuids("/api/detection-list/", controlPlan="true"),
            self._detection_uuids("/api/detection-list/"),
        )
