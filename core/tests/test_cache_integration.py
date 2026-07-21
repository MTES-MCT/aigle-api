"""Integration tests proving the cache layer is correct, isolated, and fail-open.

These exercise the real permission caches and the DetectionGeoFilterService that
gates which detections appear on the map, plus the pagination count cache. They run
with LocMemCache (cleared between tests by conftest), so the first call for a given
key is a cold miss that populates the cache and the next is a warm hit.

Setup: two regular users scoped to disjoint communes (Montpellier in Hérault vs
Paris), each with a tile set covering its commune and one detection inside it. This
lets us assert both equivalence (warm == cold) and isolation (user B can never be
served user A's detections, even after A has warmed the cache).
"""

import uuid
from datetime import date
from unittest.mock import patch

from django.contrib.gis.geos import Point, Polygon
from django.urls import reverse
from rest_framework import status

from core.constants.geo import SRID
from core.models.detection import Detection
from core.models.geo_custom_zone import GeoCustomZone
from core.models.tile_set import TileSetStatus, TileSetType
from core.permissions.tile_set import TileSetPermission
from core.permissions.user import UserPermission
from core.services.detection_geo_filter import DetectionGeoFilterService
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type,
    create_tile_set,
)
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import (
    add_user_to_group,
    create_regular_user,
    create_user_group,
    create_user_with_group,
)
from core.utils import cache as cache_utils
from core.utils.pagination import CachedCountLimitOffsetPagination

# bbox params as strings, matching how they arrive on the request
MONTPELLIER_BBOX = {
    "swLng": "3.80",
    "swLat": "43.55",
    "neLng": "3.96",
    "neLat": "43.67",
}
PARIS_BBOX = {"swLng": "2.28", "swLat": "48.80", "neLng": "2.42", "neLat": "48.92"}


def _bbox_polygon(bbox):
    polygon = Polygon.from_bbox(
        (
            float(bbox["swLng"]),
            float(bbox["swLat"]),
            float(bbox["neLng"]),
            float(bbox["neLat"]),
        )
    )
    polygon.srid = SRID
    return polygon


class CacheDetectionVisibilityTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        geo = create_complete_geo_hierarchy()
        self.montpellier = geo["communes"]["montpellier"]
        self.beziers = geo["communes"]["beziers"]
        self.paris = geo["communes"]["paris"]
        self.object_type = create_object_type(name="Pool")

        self.user_a, self.group_a, _ = create_user_with_group(
            email="cache_a@test.com",
            group_name="CacheGroupA",
            geo_zones=[self.montpellier],
        )
        self.user_b, self.group_b, _ = create_user_with_group(
            email="cache_b@test.com",
            group_name="CacheGroupB",
            geo_zones=[self.paris],
        )

        self.ts_a = create_tile_set(
            name="TS Montpellier", tile_set_type=TileSetType.BACKGROUND
        )
        self.ts_a.geo_zones.set([self.montpellier])
        self.ts_b = create_tile_set(
            name="TS Paris", tile_set_type=TileSetType.BACKGROUND
        )
        self.ts_b.geo_zones.set([self.paris])

        self.det_a = create_detection(
            detection_object=create_detection_object(
                object_type=self.object_type, commune=self.montpellier
            ),
            tile_set=self.ts_a,
            geometry=Point(3.88, 43.61, srid=SRID),
            score=0.95,
            detection_data=create_detection_data(),
        )
        self.det_b = create_detection(
            detection_object=create_detection_object(
                object_type=self.object_type, commune=self.paris
            ),
            tile_set=self.ts_b,
            geometry=Point(2.35, 48.86, srid=SRID),
            score=0.95,
            detection_data=create_detection_data(),
        )

        # the map list endpoint now requires at least one custom zone; associate det_a
        self.custom_zone_mtp = GeoCustomZone.objects.create(
            name="Zone MTP cache",
            geometry=_bbox_polygon(MONTPELLIER_BBOX),
        )
        self.det_a.detection_object.geo_custom_zones.add(self.custom_zone_mtp)

    def _service_ids(self, user, bbox, **extra):
        params = {
            **bbox,
            "objectTypesUuids": str(self.object_type.uuid),
            "interfaceDrawn": "ALL",
            **extra,
        }
        qs = DetectionGeoFilterService(user=user).apply_filters(
            Detection.objects.all(), params
        )
        return set(qs.values_list("id", flat=True))

    # --- equivalence: a warm (cached) read equals a cold (recomputed) read ---

    def test_geo_filter_warm_equals_cold(self):
        cold = self._service_ids(self.user_a, MONTPELLIER_BBOX)  # populates caches
        warm = self._service_ids(self.user_a, MONTPELLIER_BBOX)  # hits caches
        self.assertEqual(cold, warm)
        self.assertIn(self.det_a.id, cold)  # non-vacuous: A sees its detection
        self.assertNotIn(self.det_b.id, cold)

    def test_geo_union_cache_warm_equals_cold(self):
        bbox = _bbox_polygon(MONTPELLIER_BBOX)
        cold = UserPermission(user=self.user_a).get_accessible_geometry(
            intersects_geometry=bbox
        )
        warm = UserPermission(user=self.user_a).get_accessible_geometry(
            intersects_geometry=bbox
        )
        self.assertIsNotNone(cold)
        self.assertTrue(cold.equals(warm))

    # --- isolation: user B can never be served user A's data ---

    def test_user_b_cannot_see_user_a_detection_via_service(self):
        self._service_ids(self.user_a, MONTPELLIER_BBOX)  # warm A's caches
        b_ids = self._service_ids(self.user_b, MONTPELLIER_BBOX)
        self.assertEqual(b_ids, set())  # Paris-scoped B sees nothing in Montpellier
        self.assertNotIn(self.det_a.id, b_ids)
        b_own = self._service_ids(self.user_b, PARIS_BBOX)
        self.assertIn(self.det_b.id, b_own)
        self.assertNotIn(self.det_a.id, b_own)

    def test_geo_union_cache_is_scoped_per_user(self):
        bbox = _bbox_polygon(MONTPELLIER_BBOX)
        a_geom = UserPermission(user=self.user_a).get_accessible_geometry(
            intersects_geometry=bbox
        )
        self.assertIsNotNone(a_geom)  # A (Montpellier) sees the area
        b_geom = UserPermission(user=self.user_b).get_accessible_geometry(
            intersects_geometry=bbox
        )
        self.assertIsNone(b_geom)  # B (Paris) does NOT read A's cached union

    def test_detection_geo_endpoint_isolation_between_users(self):
        url = reverse("DetectionGeoViewSet-list")
        params = {
            "geoFeature": "true",
            **MONTPELLIER_BBOX,
            "objectTypesUuids": str(self.object_type.uuid),
            "interfaceDrawn": "ALL",
            "customZonesUuids": str(self.custom_zone_mtp.uuid),
        }
        self.authenticate_user(self.user_a)
        a_features = self.client.get(url, params).json().get("features", [])
        self.assertGreaterEqual(
            len(a_features), 1
        )  # A sees its detection (warms cache)

        self.authenticate_user(self.user_b)
        b_features = self.client.get(url, params).json().get("features", [])
        self.assertEqual(
            len(b_features), 0
        )  # B sees nothing of A's, despite warm cache

    # --- the filter_uuid_in bug fix: tileSetsUuids selection is actually applied ---

    def test_tilesets_uuids_filter_is_applied(self):
        # no selection -> visible (guards the [] -> None empty-case regression)
        self.assertIn(self.det_a.id, self._service_ids(self.user_a, MONTPELLIER_BBOX))
        # selecting A's own tile set -> still visible
        self.assertIn(
            self.det_a.id,
            self._service_ids(
                self.user_a, MONTPELLIER_BBOX, tileSetsUuids=str(self.ts_a.uuid)
            ),
        )
        # selecting an unrelated tile set uuid -> NOT visible (the filter is applied)
        self.assertNotIn(
            self.det_a.id,
            self._service_ids(
                self.user_a, MONTPELLIER_BBOX, tileSetsUuids=str(uuid.uuid4())
            ),
        )

    # --- count cache end-to-end: a write refreshes the cached count ---

    def test_detection_write_invalidates_pagination_count(self):
        pagination = CachedCountLimitOffsetPagination()
        queryset = Detection.objects.all()
        count_before = pagination.get_count(queryset)  # caches the count

        with self.captureOnCommitCallbacks(execute=True):
            create_detection(
                detection_object=create_detection_object(
                    object_type=self.object_type, commune=self.montpellier
                ),
                tile_set=self.ts_a,
                geometry=Point(3.88, 43.61, srid=SRID),
                score=0.9,
                detection_data=create_detection_data(),
            )

        count_after = pagination.get_count(queryset)
        self.assertEqual(count_after, count_before + 1)

    # --- fail-open: a Redis outage must recompute, never 500 or change results ---

    def test_detection_geo_endpoint_fails_open_when_cache_unavailable(self):
        self.authenticate_user(self.user_a)
        url = reverse("DetectionGeoViewSet-list")
        params = {
            "geoFeature": "true",
            **MONTPELLIER_BBOX,
            "objectTypesUuids": str(self.object_type.uuid),
            "interfaceDrawn": "ALL",
            "customZonesUuids": str(self.custom_zone_mtp.uuid),
        }
        healthy = self.client.get(url, params)
        self.assertEqual(healthy.status_code, status.HTTP_200_OK)
        baseline = len(healthy.json().get("features", []))
        self.assertGreaterEqual(baseline, 1)

        with patch.object(
            cache_utils.cache, "get", side_effect=Exception("redis down")
        ), patch.object(
            cache_utils.cache, "set", side_effect=Exception("redis down")
        ), patch.object(
            cache_utils.cache, "add", side_effect=Exception("redis down")
        ), patch.object(cache_utils.cache, "incr", side_effect=Exception("redis down")):
            degraded = self.client.get(url, params)

        self.assertEqual(degraded.status_code, status.HTTP_200_OK)
        self.assertEqual(len(degraded.json().get("features", [])), baseline)

    # --- the get_collectivity_filter ordering fix ---

    def test_collectivity_filter_ids_are_sorted(self):
        group = create_user_group(
            name="MultiZoneGroup", geo_zones=[self.montpellier, self.beziers]
        )
        user = create_regular_user(email="multizone@test.com")
        add_user_to_group(user, group)

        collectivity_filter = UserPermission(user=user).get_collectivity_filter()
        self.assertIsNotNone(collectivity_filter.commune_ids)
        self.assertEqual(len(collectivity_filter.commune_ids), 2)
        self.assertEqual(
            collectivity_filter.commune_ids, sorted(collectivity_filter.commune_ids)
        )

    def test_compute_tilesets_same_date_tiebreak_picks_highest_id(self):
        # Two BACKGROUND tile sets with the SAME date covering one zone: the
        # most-recent-per-zone window must deterministically pick the highest id
        # (the [date desc, id desc] tiebreak) instead of an arbitrary DB row.
        user, _, _ = create_user_with_group(
            email="tiebreak@test.com",
            group_name="TieBreakGroup",
            geo_zones=[self.beziers],
        )
        same_date = date(2022, 1, 1)
        ts_low = create_tile_set(
            name="Tiebreak low", date=same_date, tile_set_type=TileSetType.BACKGROUND
        )
        ts_low.geo_zones.set([self.beziers])
        ts_high = create_tile_set(
            name="Tiebreak high", date=same_date, tile_set_type=TileSetType.BACKGROUND
        )
        ts_high.geo_zones.set([self.beziers])
        self.assertGreater(ts_high.id, ts_low.id)

        result = TileSetPermission(user=user)._compute_tilesets(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            filter_tile_set_status_in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN],
            filter_has_collectivities=True,
        )
        ids = {entry["id"] for entry in result}
        self.assertIn(ts_high.id, ids)
        self.assertNotIn(ts_low.id, ids)
