import uuid
from datetime import datetime

from django.contrib.gis.geos import Point
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from core.models.geo_custom_zone import GeoCustomZone
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import (
    add_user_to_group,
    create_regular_user,
    create_super_admin,
    create_user_group,
    create_user_with_group,
)
from core.models.detection_object import DetectionObject
from core.permissions.detection import DetectionPermission
from core.tests.fixtures.detection_data import (
    create_complete_detection_setup,
    create_detection,
    create_detection_data,
    create_detection_object,
    create_detection_with_object,
    create_object_type,
    create_tile_set,
)


class DetectionObjectViewSetTests(BaseAPITestCase):
    def _get_results(self, response):
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]
        return response.data

    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        self.parcels = self.geo_data["parcels"]

        self.detection_setup = create_complete_detection_setup(parcel=self.parcels[0])
        self.detection_object = self.detection_setup["detection_object"]
        self.detection = self.detection_setup["detection"]
        self.tile_set = self.detection_setup["tile_set"]

        self.communes = self.geo_data["communes"]
        # Les lectures sont désormais bornées à la portée géographique du groupe : un
        # compte sans zone ne voit plus rien, ce qui est le correctif lui-même.
        self.user, _, _ = create_user_with_group(
            email="do-montpellier@test.com",
            group_name="Montpellier group",
            geo_zones=[self.communes["montpellier"]],
        )
        self.authenticate_user(self.user)

    def test_list_detection_objects_authenticated(self):
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(self._get_results(response), list)
        self.assertGreater(len(self._get_results(response)), 0)

    def test_list_detection_objects_unauthenticated(self):
        self.unauthenticate()
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_detection_object_detail(self):
        url = reverse(
            "DetectionObjectViewSet-detail",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["uuid"], str(self.detection_object.uuid))

    def test_filter_detection_objects_by_uuids(self):
        detection_object_2, _ = create_detection_with_object(
            x=3.89, y=43.62, object_type_name="Building"
        )

        url = reverse("DetectionObjectViewSet-list")
        uuids = f"{self.detection_object.uuid},{detection_object_2.uuid}"
        response = self.client.get(url, {"uuids": uuids})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        self.assertGreaterEqual(len(results), 2)

        result_uuids = [r["uuid"] for r in results]
        self.assertIn(str(self.detection_object.uuid), result_uuids)
        self.assertIn(str(detection_object_2.uuid), result_uuids)

    def test_filter_detection_objects_by_detection_uuids(self):
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url, {"detectionUuids": str(self.detection.uuid)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        self.assertGreater(len(results), 0)

        result_uuids = [r["uuid"] for r in results]
        self.assertIn(str(self.detection_object.uuid), result_uuids)

    def test_get_from_coordinates_missing_params(self):
        url = reverse("DetectionObjectViewSet-get-from-coordinates")

        response = self.client.get(url, {"lat": 43.61})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(url, {"lng": 3.88})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_history_action(self):
        url = reverse(
            "DetectionObjectViewSet-history",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_detection_object_includes_object_type(self):
        url = reverse(
            "DetectionObjectViewSet-detail",
            kwargs={"uuid": str(self.detection_object.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        has_object_type = (
            "objectType" in response.data or "object_type" in response.data
        )
        self.assertTrue(has_object_type)

    def test_detection_object_with_detail_param(self):
        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url, {"detail": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_nonexistent_detection_object_returns_404(self):
        fake_uuid = uuid.uuid4()
        url = reverse("DetectionObjectViewSet-detail", kwargs={"uuid": str(fake_uuid)})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_detection_object_ordering(self):
        tile_set_old = create_tile_set(
            name="Old TileSet",
            date=timezone.make_aware(datetime(2020, 1, 1)),
        )
        tile_set_new = create_tile_set(
            name="New TileSet",
            date=timezone.make_aware(datetime(2024, 1, 1)),
        )

        old_obj, _ = create_detection_with_object(
            x=3.87,
            y=43.60,
            tile_set=tile_set_old,
            object_type_name="Old Detection Type",
        )
        new_obj, _ = create_detection_with_object(
            x=3.89,
            y=43.62,
            tile_set=tile_set_new,
            object_type_name="New Detection Type",
        )

        url = reverse("DetectionObjectViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)

        if len(results) >= 2:
            uuids = [r["uuid"] for r in results]
            new_obj_index = next(
                (i for i, u in enumerate(uuids) if u == str(new_obj.uuid)), None
            )
            old_obj_index = next(
                (i for i, u in enumerate(uuids) if u == str(old_obj.uuid)), None
            )

            if new_obj_index is not None and old_obj_index is not None:
                self.assertLess(new_obj_index, old_obj_index)


class DetectionObjectScopeTests(BaseAPITestCase):
    """Les lectures étaient hors périmètre : n'importe quel compte authentifié listait
    et consultait les objets de tout le territoire (adresse, commentaire, parcelle,
    historique). Elles suivent maintenant la même règle que les écritures."""

    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        self.communes = self.geo_data["communes"]

        self.montpellier_object = create_detection_object(
            object_type=create_object_type(name="Piscine"),
            commune=self.communes["montpellier"],
        )
        self.nimes_object = create_detection_object(
            object_type=create_object_type(name="Cabane"),
            commune=self.communes["nimes"],
        )

        self.user, _, _ = create_user_with_group(
            email="scope-montpellier@test.com",
            group_name="Montpellier scope group",
            geo_zones=[self.communes["montpellier"]],
        )
        self.authenticate_user(self.user)

    def _uuids(self, response):
        results = response.data
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        return [result["uuid"] for result in results]

    def test_list_excludes_objects_outside_perimeter(self):
        response = self.client.get(reverse("DetectionObjectViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        uuids = self._uuids(response)
        self.assertIn(str(self.montpellier_object.uuid), uuids)
        self.assertNotIn(str(self.nimes_object.uuid), uuids)

    def test_uuids_filter_cannot_reach_outside_perimeter(self):
        response = self.client.get(
            reverse("DetectionObjectViewSet-list"),
            {"uuids": str(self.nimes_object.uuid)},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._uuids(response), [])

    def test_retrieve_outside_perimeter_returns_404(self):
        response = self.client.get(
            reverse(
                "DetectionObjectViewSet-detail",
                kwargs={"uuid": str(self.nimes_object.uuid)},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_history_outside_perimeter_returns_404(self):
        response = self.client.get(
            reverse(
                "DetectionObjectViewSet-history",
                kwargs={"uuid": str(self.nimes_object.uuid)},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_super_admin_still_sees_everything(self):
        self.authenticate_user(create_super_admin(email="scope-sa@test.com"))

        response = self.client.get(reverse("DetectionObjectViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(str(self.nimes_object.uuid), self._uuids(response))


class FromCoordinatesCustomZoneTests(BaseAPITestCase):
    """A point outside every accessible custom zone (zone urbaine) cannot be searched."""

    def setUp(self):
        super().setUp()
        self.user = create_super_admin(email="fromcoord@test.com")
        self.authenticate_user(self.user)
        self.url = reverse("DetectionObjectViewSet-get-from-coordinates")

    def _is_urban_block(self, response):
        return (
            response.status_code == status.HTTP_403_FORBIDDEN
            and isinstance(response.data, dict)
            and response.data.get("code") == "OUTSIDE_CUSTOM_ZONE"
        )

    def test_returns_outside_custom_zone_in_urban_area(self):
        # an active zone exists elsewhere, but the queried point is covered by none
        GeoCustomZone.objects.create(
            name="Elsewhere",
            geometry=self.create_bbox_polygon(4.10, 43.60, 4.12, 43.62),
        )
        response = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertTrue(self._is_urban_block(response))

    def test_no_active_zone_anywhere_blocks_search(self):
        response = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertTrue(self._is_urban_block(response))

    def test_point_inside_custom_zone_is_not_blocked_as_urban(self):
        GeoCustomZone.objects.create(
            name="Covering",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.89, 43.62),
        )
        response = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        # passes the custom-zone gate; downstream may 403 (no tile set) or 200/null,
        # but it must NOT be the urban block.
        self.assertFalse(self._is_urban_block(response))

    def test_inactive_covering_zone_still_blocks(self):
        GeoCustomZone.objects.create(
            name="Inactive covering",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.89, 43.62),
            geo_custom_zone_status="INACTIVE",
        )
        response = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertTrue(self._is_urban_block(response))

    def test_scoped_to_user_groups_custom_zones(self):
        # The covering zone is real and active, but a regular user only reaches it if
        # one of their user groups grants it — the heart of "accessible by the user".
        covering_zone = GeoCustomZone.objects.create(
            name="Group covering",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.89, 43.62),
        )
        with_access = create_regular_user(email="withzone@test.com")
        group = create_user_group(name="Zone group")
        group.geo_custom_zones.add(covering_zone)
        add_user_to_group(with_access, group)

        without_access = create_regular_user(email="nozone@test.com")

        self.authenticate_user(without_access)
        blocked = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertTrue(self._is_urban_block(blocked))

        self.authenticate_user(with_access)
        allowed = self.client.get(self.url, {"lat": 43.61, "lng": 3.88})
        self.assertFalse(self._is_urban_block(allowed))


class DetectionObjectLegacyReadScopeTests(BaseAPITestCase):
    """Objets hérités, dont la commune n'a jamais été résolue : leur lecture passe par le
    repli géométrique. Les fixtures ne l'exerçaient jamais positivement pour un groupe
    départemental, le point par défaut (Montpellier, 3.88) étant hors de l'Hérault."""

    def setUp(self):
        super().setUp()
        self.geo_data = create_complete_geo_hierarchy()
        herault = self.geo_data["departments"]["herault"]

        # (3.3, 43.5) est dans l'Hérault des fixtures (2.9-3.7 / 43.2-43.9).
        self.legacy_inside = create_detection_object(
            object_type=create_object_type(name="Cabane")
        )
        create_detection(
            detection_object=self.legacy_inside,
            geometry=Point(3.3, 43.5, srid=4326),
            detection_data=create_detection_data(),
        )
        # Nîmes, dans le Gard.
        self.legacy_outside = create_detection_object(
            object_type=create_object_type(name="Mobil-home")
        )
        create_detection(
            detection_object=self.legacy_outside,
            geometry=Point(4.36, 43.84, srid=4326),
            detection_data=create_detection_data(),
        )

        self.user, _, _ = create_user_with_group(
            email="legacy-herault@test.com",
            group_name="DDTM 34 legacy",
            geo_zones=[herault],
        )
        self.authenticate_user(self.user)

    def _detail(self, detection_object):
        return self.client.get(
            reverse(
                "DetectionObjectViewSet-detail",
                kwargs={"uuid": str(detection_object.uuid)},
            )
        )

    def test_legacy_object_inside_department_is_readable(self):
        self.assertEqual(
            self._detail(self.legacy_inside).status_code, status.HTTP_200_OK
        )

    def test_legacy_object_outside_department_returns_404(self):
        self.assertEqual(
            self._detail(self.legacy_outside).status_code, status.HTTP_404_NOT_FOUND
        )

    def test_list_keeps_legacy_inside_and_drops_legacy_outside(self):
        response = self.client.get(reverse("DetectionObjectViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        uuids = {result["uuid"] for result in results}
        self.assertIn(str(self.legacy_inside.uuid), uuids)
        self.assertNotIn(str(self.legacy_outside.uuid), uuids)

    def test_legacy_fallback_is_not_a_hashed_subplan(self):
        """Haché, le repli se calcule sur TOUTES les détections héritées de France dès
        que l'objet évalué a une commune NULL, même pour un retrieve : 35 à 73 s mesurés
        sur un volume réaliste, contre ~1 ms corrélé ligne par ligne."""
        queryset = DetectionObject.objects.filter(
            DetectionPermission(user=self.user).get_readable_objects_q()
        ).filter(uuid=self.legacy_inside.uuid)

        sql, params = queryset.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN " + sql, params)
            plan = "\n".join(row[0] for row in cursor.fetchall())

        # Garde contre un passage à vide si le format du plan change.
        self.assertRegex(plan, r"commune_id IS NULL\) AND \(", plan)
        self.assertNotRegex(plan, r"IS NULL\) AND \(hashed SubPlan", plan)
        self.assertTrue(queryset.exists())
