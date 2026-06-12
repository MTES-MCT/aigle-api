import datetime
from uuid import uuid4

from django.contrib.gis.geos import Polygon
from django.urls import reverse
from rest_framework import status

from core.models.detection_data import DetectionValidationStatusChangeReason
from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneStatus,
    GeoCustomZoneType,
)
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type,
    create_tile_set,
)
from core.tests.fixtures.geo_data import (
    create_beziers_commune,
    create_gard_department,
    create_herault_department,
    create_montpellier_commune,
    create_nimes_commune,
    create_occitanie_region,
    create_parcel,
)
from core.tests.fixtures.users import (
    add_user_to_group,
    create_admin,
    create_regular_user,
    create_super_admin,
    create_user,
    create_user_group,
)

URL_LIST = "StatisticsDeployedDataView"
URL_DETAIL = "StatisticsDeployedDataDetailView"


class StatisticsDeployedDataViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="ddadmin@test.com")
        self.admin = create_admin(email="ddmod@test.com")
        self.regular = create_regular_user(email="dduser@test.com")

        region = create_occitanie_region()
        self.herault = create_herault_department(region=region)
        self.gard = create_gard_department(region=region)  # left without detections
        self.montpellier = create_montpellier_commune(department=self.herault)
        self.beziers = create_beziers_commune(department=self.herault)
        self.nimes = create_nimes_commune(department=self.gard)

        # Tile set associated to the department via geo_zones -> it is the department's
        # "fond de carte" (the association, NOT Detection.tile_set, drives this).
        self.tile_set = create_tile_set(
            name="Hérault 2024", date=datetime.date(2024, 1, 9)
        )
        self.tile_set.geo_zones.add(self.herault)

        # Two detections in Montpellier (via two detection objects) -> Hérault deployed.
        object_type = create_object_type(name="Pool")
        for _ in range(2):
            detection_object = create_detection_object(
                object_type=object_type, commune=self.montpellier
            )
            create_detection(detection_object=detection_object, tile_set=self.tile_set)

        # A parcel in the department.
        create_parcel(commune=self.montpellier, id_parcellaire="341720000001")

        # A user group associated to the department, with two members.
        self.group_department = create_user_group(
            name="DDTM Hérault", geo_zones=[self.herault]
        )
        self.member_1 = create_user(email="member1@test.com")
        self.member_2 = create_user(email="member2@test.com")
        add_user_to_group(self.member_1, self.group_department)
        add_user_to_group(self.member_2, self.group_department)

        # A user group associated to a COMMUNE of the department; member_1 is shared with
        # the department group (so distinct user count is 2, not 3).
        self.group_commune = create_user_group(
            name="Collectivité Montpellier", geo_zones=[self.montpellier]
        )
        add_user_to_group(self.member_1, self.group_commune)

        # A categorized custom zone associated to a commune of the department.
        self.category = GeoCustomZoneCategory.objects.create(
            name="PLU", color="#123456", name_short="PLU"
        )
        self.custom_zone = GeoCustomZone.objects.create(
            name="Zone PLU Montpellier",
            geo_custom_zone_type=GeoCustomZoneType.COMMON,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
            geo_custom_zone_category=self.category,
            color="#AA1122",
            geometry=Polygon(
                [(3.8, 43.5), (3.9, 43.5), (3.9, 43.6), (3.8, 43.6), (3.8, 43.5)],
                srid=4326,
            ),
        )
        self.custom_zone.geo_zones.add(self.montpellier)

    # --- helpers ---

    def _detail_url(self, uuid):
        return reverse(URL_DETAIL, kwargs={"uuid": str(uuid)})

    def _get_list(self, params=None):
        self.authenticate_user(self.super_admin)
        response = self.client.get(reverse(URL_LIST), params or {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def _get_detail(self, uuid, params=None):
        self.authenticate_user(self.super_admin)
        response = self.client.get(self._detail_url(uuid), params or {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # --- list: permissions ---

    def test_list_unauthenticated_returns_401(self):
        response = self.client.get(reverse(URL_LIST))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_regular_user_forbidden(self):
        self.authenticate_user(self.regular)
        response = self.client.get(reverse(URL_LIST))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_admin_user_forbidden(self):
        self.authenticate_user(self.admin)
        response = self.client.get(reverse(URL_LIST))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_super_admin_allowed(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(reverse(URL_LIST))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- detail: permissions ---

    def test_detail_unauthenticated_returns_401(self):
        response = self.client.get(self._detail_url(self.herault.uuid))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_detail_regular_user_forbidden(self):
        self.authenticate_user(self.regular)
        response = self.client.get(self._detail_url(self.herault.uuid))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_detail_super_admin_allowed(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(self._detail_url(self.herault.uuid))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_detail_unknown_uuid_returns_404(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(self._detail_url(uuid4()))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_non_deployed_department_returns_404(self):
        # Gard has no detections, so it is not deployed and has no detail page.
        self.authenticate_user(self.super_admin)
        response = self.client.get(self._detail_url(self.gard.uuid))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- list: content ---

    def test_only_departments_with_detections_returned(self):
        names = {department["name"] for department in self._get_list()}
        self.assertIn("Hérault", names)
        self.assertNotIn("Gard", names)

    def test_list_summary_fields(self):
        herault = next(d for d in self._get_list() if d["name"] == "Hérault")
        self.assertEqual(herault["uuid"], str(self.herault.uuid))
        self.assertEqual(herault["communesWithDetectionsCount"], 1)
        # distinct users across both groups (member_1 is shared) -> 2
        self.assertEqual(herault["usersCount"], 2)
        self.assertEqual(herault["tileSetYears"], ["2024"])

    def test_list_row_has_no_nested_detail(self):
        # The list stays lightweight; nested breakdowns belong to the detail endpoint.
        herault = next(d for d in self._get_list() if d["name"] == "Hérault")
        for key in (
            "communes",
            "userGroups",
            "customZones",
            "tileSets",
            "parcelsCount",
        ):
            self.assertNotIn(key, herault)

    def test_search_q_matches_department_name(self):
        data = self._get_list({"q": "hér"})
        self.assertEqual({d["name"] for d in data}, {"Hérault"})

    def test_search_q_no_match_returns_empty(self):
        self.assertEqual(self._get_list({"q": "zzzznomatch"}), [])

    def test_min_commune_detections_filter(self):
        # Béziers gets a single detection -> Hérault has two deployed communes.
        beziers_object = create_detection_object(
            object_type=create_object_type(name="Pool"), commune=self.beziers
        )
        create_detection(detection_object=beziers_object, tile_set=self.tile_set)

        herault = next(d for d in self._get_list() if d["name"] == "Hérault")
        self.assertEqual(herault["communesWithDetectionsCount"], 2)

        # Threshold 2 -> only Montpellier qualifies.
        herault = next(
            d
            for d in self._get_list({"minCommuneDetections": 2})
            if d["name"] == "Hérault"
        )
        self.assertEqual(herault["communesWithDetectionsCount"], 1)

        # Threshold 3 -> no commune qualifies -> Hérault dropped entirely.
        self.assertEqual(self._get_list({"minCommuneDetections": 3}), [])

    # --- detail: content ---

    def test_detail_aggregated_fields(self):
        herault = self._get_detail(self.herault.uuid)
        self.assertEqual(herault["uuid"], str(self.herault.uuid))
        self.assertEqual(herault["parcelsCount"], 1)
        self.assertEqual(herault["communesWithDetectionsCount"], 1)
        # No detection was updated via SITADEL in the base setup.
        self.assertEqual(herault["sitadelUpdatedDetectionsCount"], 0)

        self.assertEqual(len(herault["communes"]), 1)
        commune = herault["communes"][0]
        self.assertEqual(commune["name"], "Montpellier")
        self.assertEqual(commune["uuid"], str(self.montpellier.uuid))
        self.assertEqual(commune["detectionsCount"], 2)

    def test_detail_sitadel_updated_detections_count(self):
        # Two more detections across both communes of the department, only some of which
        # were last touched by the SITADEL import; deleted ones must not be counted.
        object_type = create_object_type(name="Pool")

        # Montpellier: one SITADEL-updated detection.
        montpellier_object = create_detection_object(
            object_type=object_type, commune=self.montpellier
        )
        create_detection(
            detection_object=montpellier_object,
            tile_set=self.tile_set,
            detection_data=create_detection_data(
                detection_validation_status_change_reason=DetectionValidationStatusChangeReason.SITADEL
            ),
        )

        # Béziers (another commune of Hérault): one SITADEL-updated detection -> the
        # count must roll up across all the department's communes.
        beziers_object = create_detection_object(
            object_type=object_type, commune=self.beziers
        )
        create_detection(
            detection_object=beziers_object,
            tile_set=self.tile_set,
            detection_data=create_detection_data(
                detection_validation_status_change_reason=DetectionValidationStatusChangeReason.SITADEL
            ),
        )

        # A detection updated for another reason -> must NOT be counted.
        create_detection(
            detection_object=montpellier_object,
            tile_set=self.tile_set,
            detection_data=create_detection_data(
                detection_validation_status_change_reason=DetectionValidationStatusChangeReason.EXTERNAL_API
            ),
        )

        herault = self._get_detail(self.herault.uuid)
        self.assertEqual(herault["sitadelUpdatedDetectionsCount"], 2)

    def test_detail_user_groups_and_members(self):
        herault = self._get_detail(self.herault.uuid)
        groups_by_name = {g["name"]: g for g in herault["userGroups"]}
        # both the department-level and the commune-level group are present
        self.assertIn("DDTM Hérault", groups_by_name)
        self.assertIn("Collectivité Montpellier", groups_by_name)

        emails = {user["email"] for user in groups_by_name["DDTM Hérault"]["users"]}
        self.assertEqual(emails, {"member1@test.com", "member2@test.com"})

    def test_detail_custom_zones(self):
        herault = self._get_detail(self.herault.uuid)
        self.assertEqual(len(herault["customZones"]), 1)
        custom_zone = herault["customZones"][0]
        self.assertEqual(custom_zone["uuid"], str(self.custom_zone.uuid))
        self.assertEqual(custom_zone["categoryName"], "PLU")
        # category color takes precedence over the zone's own color
        self.assertEqual(custom_zone["color"], "#123456")

    def test_detail_custom_zone_without_category(self):
        zone = GeoCustomZone.objects.create(
            name="Zone sans catégorie",
            geo_custom_zone_type=GeoCustomZoneType.COMMON,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
            geo_custom_zone_category=None,
            color="#FF0000",
            geometry=Polygon(
                [(3.8, 43.5), (3.9, 43.5), (3.9, 43.6), (3.8, 43.6), (3.8, 43.5)],
                srid=4326,
            ),
        )
        zone.geo_zones.add(self.montpellier)

        herault = self._get_detail(self.herault.uuid)
        custom_zone = next(
            z for z in herault["customZones"] if z["uuid"] == str(zone.uuid)
        )
        self.assertIsNone(custom_zone["categoryName"])
        self.assertEqual(custom_zone["name"], "Zone sans catégorie")
        self.assertEqual(custom_zone["color"], "#FF0000")

    def test_detail_tile_sets_from_geo_zone_association(self):
        # Associated to the department but used by NO detection -> still appears.
        associated_unused = create_tile_set(
            name="Associée 2099", date=datetime.date(2099, 1, 1)
        )
        associated_unused.geo_zones.add(self.herault)
        # Used by a detection but NOT associated via geo_zones -> must NOT appear.
        used_unassociated = create_tile_set(
            name="Utilisée non associée 2019", date=datetime.date(2019, 1, 1)
        )
        obj = create_detection_object(
            object_type=create_object_type(name="Pool"), commune=self.montpellier
        )
        create_detection(detection_object=obj, tile_set=used_unassociated)

        herault = self._get_detail(self.herault.uuid)
        names = {t["name"] for t in herault["tileSets"]}
        self.assertIn("Hérault 2024", names)
        self.assertIn("Associée 2099", names)
        self.assertNotIn("Utilisée non associée 2019", names)

        # tile set rows carry uuid + date (for the frontend link + badge)
        tile_set = next(t for t in herault["tileSets"] if t["name"] == "Hérault 2024")
        self.assertEqual(tile_set["uuid"], str(self.tile_set.uuid))
        self.assertEqual(tile_set["date"], "2024-01-09")

    def test_detail_tile_set_commune_association(self):
        # A tile set associated to a COMMUNE of the department surfaces under it.
        commune_tile_set = create_tile_set(
            name="Montpellier 2022", date=datetime.date(2022, 1, 1)
        )
        commune_tile_set.geo_zones.add(self.montpellier)

        herault = self._get_detail(self.herault.uuid)
        self.assertIn("Montpellier 2022", {t["name"] for t in herault["tileSets"]})

    def test_detail_tile_sets_sorted_by_date_desc(self):
        older = create_tile_set(name="Hérault 2018", date=datetime.date(2018, 1, 1))
        older.geo_zones.add(self.herault)

        herault = self._get_detail(self.herault.uuid)
        dates = [t["date"] for t in herault["tileSets"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_detail_associations_of_other_department_not_leaked(self):
        # Associations attached only to a Gard commune must not surface under Hérault.
        gard_group = create_user_group(name="DDTM Gard", geo_zones=[self.nimes])
        add_user_to_group(self.member_1, gard_group)
        gard_tile_set = create_tile_set(
            name="Gard 2021", date=datetime.date(2021, 1, 1)
        )
        gard_tile_set.geo_zones.add(self.nimes)

        herault = self._get_detail(self.herault.uuid)
        self.assertNotIn(
            "DDTM Gard", {group["name"] for group in herault["userGroups"]}
        )
        self.assertNotIn("Gard 2021", {t["name"] for t in herault["tileSets"]})

    def test_detail_respects_min_commune_detections(self):
        beziers_object = create_detection_object(
            object_type=create_object_type(name="Pool"), commune=self.beziers
        )
        create_detection(detection_object=beziers_object, tile_set=self.tile_set)

        # No threshold -> both communes in the detail.
        herault = self._get_detail(self.herault.uuid)
        self.assertEqual(
            {c["name"] for c in herault["communes"]}, {"Montpellier", "Béziers"}
        )

        # Threshold 2 -> only Montpellier, consistent with the list row.
        herault = self._get_detail(self.herault.uuid, {"minCommuneDetections": 2})
        self.assertEqual([c["name"] for c in herault["communes"]], ["Montpellier"])
        self.assertEqual(herault["communesWithDetectionsCount"], 1)

    def test_detail_min_commune_detections_drops_department_404(self):
        # Montpellier has 2 detections; threshold 3 leaves no qualifying commune.
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            self._detail_url(self.herault.uuid), {"minCommuneDetections": 3}
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
