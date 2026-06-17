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
from core.services.deployed_data import DeployedDataService
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
from core.utils.cache import safe_cache_get

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

        create_parcel(commune=self.montpellier, id_parcellaire="341720000001")

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

    def test_detail_aggregated_fields(self):
        herault = self._get_detail(self.herault.uuid)
        self.assertEqual(herault["uuid"], str(self.herault.uuid))
        self.assertEqual(herault["parcelsCount"], 1)
        self.assertEqual(herault["communesWithDetectionsCount"], 1)
        # No parcel was updated via SITADEL in the base setup.
        self.assertEqual(herault["sitadelUpdatedParcelsCount"], 0)

        self.assertEqual(len(herault["communes"]), 1)
        commune = herault["communes"][0]
        self.assertEqual(commune["name"], "Montpellier")
        self.assertEqual(commune["uuid"], str(self.montpellier.uuid))
        # Per commune we count OBJECTS: two objects in Montpellier, neither in a zone.
        self.assertEqual(commune["detectionObjectsCount"], 2)
        self.assertEqual(commune["detectionObjectsInCustomZoneCount"], 0)

        # The base setup has two detections, both on "Hérault 2024", neither in a zone.
        self.assertEqual(len(herault["detectionsByTileSet"]), 1)
        by_tile_set = herault["detectionsByTileSet"][0]
        self.assertEqual(by_tile_set["name"], "Hérault 2024")
        self.assertEqual(by_tile_set["uuid"], str(self.tile_set.uuid))
        self.assertEqual(by_tile_set["detectionsCount"], 2)
        self.assertEqual(by_tile_set["detectionsInCustomZoneCount"], 0)

    def test_detail_sitadel_updated_parcels_count(self):
        # A parcel is "updated by SITADEL" when one of its detection objects carries a
        # detection whose detection_data change reason is SITADEL. The figure counts
        # DISTINCT parcels and rolls up across the department's communes.
        object_type = create_object_type(name="Pool")

        # Montpellier: one parcel updated by SITADEL, reached through TWO detection
        # objects/detections on the SAME parcel -> still counted once.
        montpellier_parcel = create_parcel(
            commune=self.montpellier, id_parcellaire="341720000010"
        )
        for _ in range(2):
            obj = create_detection_object(
                object_type=object_type,
                commune=self.montpellier,
                parcel=montpellier_parcel,
            )
            create_detection(
                detection_object=obj,
                tile_set=self.tile_set,
                detection_data=create_detection_data(
                    detection_validation_status_change_reason=DetectionValidationStatusChangeReason.SITADEL
                ),
            )

        # Béziers (another commune of Hérault): a second parcel updated by SITADEL ->
        # the count must roll up across all the department's communes.
        beziers_parcel = create_parcel(
            commune=self.beziers, id_parcellaire="340320000020"
        )
        beziers_object = create_detection_object(
            object_type=object_type, commune=self.beziers, parcel=beziers_parcel
        )
        create_detection(
            detection_object=beziers_object,
            tile_set=self.tile_set,
            detection_data=create_detection_data(
                detection_validation_status_change_reason=DetectionValidationStatusChangeReason.SITADEL
            ),
        )

        # A parcel touched for another reason -> must NOT be counted.
        other_parcel = create_parcel(
            commune=self.montpellier, id_parcellaire="341720000030"
        )
        other_object = create_detection_object(
            object_type=object_type, commune=self.montpellier, parcel=other_parcel
        )
        create_detection(
            detection_object=other_object,
            tile_set=self.tile_set,
            detection_data=create_detection_data(
                detection_validation_status_change_reason=DetectionValidationStatusChangeReason.EXTERNAL_API
            ),
        )

        # A SITADEL detection whose object has NO parcel -> nothing to count.
        parcelless_object = create_detection_object(
            object_type=object_type, commune=self.montpellier
        )
        create_detection(
            detection_object=parcelless_object,
            tile_set=self.tile_set,
            detection_data=create_detection_data(
                detection_validation_status_change_reason=DetectionValidationStatusChangeReason.SITADEL
            ),
        )

        herault = self._get_detail(self.herault.uuid)
        self.assertEqual(herault["sitadelUpdatedParcelsCount"], 2)

    def test_detail_commune_objects_in_custom_zone_count(self):
        # Per-commune OBJECT counts: total, and the subset inside at least one ZAE.
        object_type = create_object_type(name="Pool")

        # An object in the existing custom zone AND a second one -> it must be counted
        # once, not once per zone. (Objects count regardless of how many detections.)
        in_zone = create_detection_object(
            object_type=object_type, commune=self.montpellier
        )
        in_zone.geo_custom_zones.add(self.custom_zone)
        other_zone = GeoCustomZone.objects.create(
            name="Zone PLU 2",
            geo_custom_zone_type=GeoCustomZoneType.COMMON,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
            color="#00FF00",
            geometry=Polygon(
                [(3.8, 43.5), (3.9, 43.5), (3.9, 43.6), (3.8, 43.6), (3.8, 43.5)],
                srid=4326,
            ),
        )
        in_zone.geo_custom_zones.add(other_zone)

        # An object in NO custom zone -> excluded from the in-zae count.
        create_detection_object(object_type=object_type, commune=self.montpellier)

        herault = self._get_detail(self.herault.uuid)
        commune = next(c for c in herault["communes"] if c["name"] == "Montpellier")
        # base setup (2) + the two objects created here = 4 objects total
        self.assertEqual(commune["detectionObjectsCount"], 4)
        # only `in_zone` falls inside a custom zone (counted once despite two zones)
        self.assertEqual(commune["detectionObjectsInCustomZoneCount"], 1)

    def test_detail_detections_by_tile_set(self):
        # Per-tile-set detection counts, split by whether the detection's object sits in
        # a custom zone, rolled up across the department's communes.
        object_type = create_object_type(name="Pool")
        tile_set_b = create_tile_set(
            name="Hérault 2023", date=datetime.date(2023, 1, 1)
        )

        # Montpellier, "Hérault 2024": one object IN a custom zone. Giving it a SECOND
        # zone must not double-count its single detection (M2M join would multiply it).
        in_zone_obj = create_detection_object(
            object_type=object_type, commune=self.montpellier
        )
        in_zone_obj.geo_custom_zones.add(self.custom_zone)
        second_zone = GeoCustomZone.objects.create(
            name="Zone PLU bis",
            geo_custom_zone_type=GeoCustomZoneType.COMMON,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
            color="#00FF00",
            geometry=Polygon(
                [(3.8, 43.5), (3.9, 43.5), (3.9, 43.6), (3.8, 43.6), (3.8, 43.5)],
                srid=4326,
            ),
        )
        in_zone_obj.geo_custom_zones.add(second_zone)
        create_detection(detection_object=in_zone_obj, tile_set=self.tile_set)

        # Béziers, "Hérault 2024": one object OUT of any custom zone -> the per-tile-set
        # count must roll up across all the department's communes.
        beziers_obj = create_detection_object(
            object_type=object_type, commune=self.beziers
        )
        create_detection(detection_object=beziers_obj, tile_set=self.tile_set)

        # Montpellier, "Hérault 2023": one object IN a custom zone.
        other_in_zone = create_detection_object(
            object_type=object_type, commune=self.montpellier
        )
        other_in_zone.geo_custom_zones.add(self.custom_zone)
        create_detection(detection_object=other_in_zone, tile_set=tile_set_b)

        herault = self._get_detail(self.herault.uuid)
        by_name = {t["name"]: t for t in herault["detectionsByTileSet"]}

        # "Hérault 2024": base setup added 2 detections (Montpellier, no zone); this test
        # adds 1 in-zone (Montpellier, counted once despite two zones) + 1 out-of-zone
        # (Béziers) -> 4 total, 1 in ZAE.
        self.assertEqual(by_name["Hérault 2024"]["detectionsCount"], 4)
        self.assertEqual(by_name["Hérault 2024"]["detectionsInCustomZoneCount"], 1)

        # "Hérault 2023": a single in-zone detection.
        self.assertEqual(by_name["Hérault 2023"]["detectionsCount"], 1)
        self.assertEqual(by_name["Hérault 2023"]["detectionsInCustomZoneCount"], 1)

        # Sorted by tile-set date, newest first.
        dates = [t["date"] for t in herault["detectionsByTileSet"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_list_does_not_compute_department_detail(self):
        # The list view must serve the lean summary only and never compute/persist a
        # per-department detail (the whole point of the two-tier cache).
        self._get_list()
        self.assertIsNone(
            safe_cache_get(DeployedDataService._detail_cache_key(self.herault.uuid))
        )

    def test_detail_cache_is_bounded_and_refreshed_by_warm(self):
        # First access computes and caches the department detail.
        herault = self._get_detail(self.herault.uuid)
        self.assertEqual(herault["communes"][0]["detectionObjectsCount"], 2)

        # A new object lands in Montpellier. This slow-moving cache is intentionally NOT
        # invalidated per write, so the stale value is still served.
        create_detection_object(
            object_type=create_object_type(name="Pool"), commune=self.montpellier
        )
        herault = self._get_detail(self.herault.uuid)
        self.assertEqual(herault["communes"][0]["detectionObjectsCount"], 2)

        # The warm refresh bumps the version, so the detail recomputes on next access.
        DeployedDataService.refresh_cache()
        herault = self._get_detail(self.herault.uuid)
        self.assertEqual(herault["communes"][0]["detectionObjectsCount"], 3)

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
