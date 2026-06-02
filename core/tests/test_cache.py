"""Tests for the version-based cache layer (core/utils/cache.py) and the
cache-invalidation signals (core/signals.py).

Invalidation works by bumping a version counter that is embedded in the cache
key, so "invalidated" means "the key the next request builds is different from
the one used before". These tests assert that property rather than poking at
Redis internals.
"""

from unittest.mock import patch

from django.test import TestCase

from core.models import User, UserUserGroup
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.geo_region import GeoRegion
from core.models.user_group import UserGroupRight
from core.services.user import UserService
from core.tests.fixtures.detection_data import (
    create_detection_object,
    create_object_type,
)
from core.tests.fixtures.users import (
    create_regular_user,
    create_super_admin,
    create_user_group,
    create_user_with_group,
)
from core.utils import cache as cache_utils
from core.utils.cache import (
    get_count_cache_version,
    get_tileset_filter_cache_key,
    get_user_geo_cache_key,
    invalidate_caches_for_group,
    invalidate_caches_for_user,
    invalidate_count_caches,
    invalidate_tileset_filter_caches,
    invalidate_user_geo_caches,
    safe_cache_get,
    safe_cache_set,
)
from core.utils.pagination import generate_query_cache_key


class CacheVersioningTests(TestCase):
    def test_user_invalidation_changes_user_geo_key(self):
        key1 = get_user_geo_cache_key(1, None)
        invalidate_caches_for_user(1)
        self.assertNotEqual(key1, get_user_geo_cache_key(1, None))

    def test_user_invalidation_is_scoped_to_that_user(self):
        other = get_user_geo_cache_key(2, None)
        invalidate_caches_for_user(1)
        self.assertEqual(other, get_user_geo_cache_key(2, None))

    def test_global_geo_invalidation_changes_every_user_geo_key(self):
        key_a = get_user_geo_cache_key(1, None)
        key_b = get_user_geo_cache_key(2, None)
        invalidate_user_geo_caches()
        self.assertNotEqual(key_a, get_user_geo_cache_key(1, None))
        self.assertNotEqual(key_b, get_user_geo_cache_key(2, None))

    def test_tileset_invalidation_changes_tileset_filter_key(self):
        key1 = get_tileset_filter_cache_key(1, None, "hash")
        invalidate_tileset_filter_caches()
        self.assertNotEqual(key1, get_tileset_filter_cache_key(1, None, "hash"))

    def test_group_invalidation_changes_group_scoped_key(self):
        key1 = get_user_geo_cache_key(1, scoped_user_group_id=5)
        invalidate_caches_for_group(5)
        self.assertNotEqual(key1, get_user_geo_cache_key(1, scoped_user_group_id=5))

    def test_count_invalidation_bumps_version(self):
        v1 = get_count_cache_version()
        invalidate_count_caches()
        self.assertEqual(get_count_cache_version(), v1 + 1)

    def test_pagination_key_changes_after_count_invalidation(self):
        queryset = User.objects.all()
        key1 = generate_query_cache_key(queryset)
        invalidate_count_caches()
        self.assertNotEqual(key1, generate_query_cache_key(queryset))

    def test_count_cache_key_is_user_scoped(self):
        # Two users must never share a cached count, even for identical SQL.
        queryset = User.objects.all()
        self.assertNotEqual(
            generate_query_cache_key(queryset, scope="u1"),
            generate_query_cache_key(queryset, scope="u2"),
        )


class CacheFailOpenTests(TestCase):
    """A cache backend outage must degrade to recompute, never raise."""

    def test_safe_get_returns_default_on_backend_error(self):
        with patch.object(cache_utils.cache, "get", side_effect=Exception("down")):
            self.assertIsNone(safe_cache_get("k"))
            self.assertEqual(safe_cache_get("k", "fallback"), "fallback")

    def test_safe_set_swallows_backend_error(self):
        with patch.object(cache_utils.cache, "set", side_effect=Exception("down")):
            safe_cache_set("k", "v", timeout=10)  # must not raise

    def test_increment_swallows_backend_error(self):
        with patch.object(cache_utils.cache, "incr", side_effect=Exception("down")):
            invalidate_count_caches()  # must not raise

    def test_key_building_falls_back_to_version_one_on_outage(self):
        with patch.object(
            cache_utils.cache, "get", side_effect=Exception("down")
        ), patch.object(
            cache_utils.cache, "set", side_effect=Exception("down")
        ), patch.object(cache_utils.cache, "add", side_effect=Exception("down")):
            self.assertEqual(
                get_user_geo_cache_key(1, None), "aigle:v1:user_geo:1:1:1:0"
            )


class CacheSignalTests(TestCase):
    """Signals defer invalidation to transaction.on_commit, so each test runs the
    triggering write inside captureOnCommitCallbacks(execute=True)."""

    def test_membership_creation_invalidates_user(self):
        user = create_regular_user()
        group = create_user_group(name="G1")
        key_before = get_user_geo_cache_key(user.id, None)

        with self.captureOnCommitCallbacks(execute=True):
            UserUserGroup.objects.create(
                user=user,
                user_group=group,
                user_group_rights=[UserGroupRight.READ],
            )

        self.assertNotEqual(key_before, get_user_geo_cache_key(user.id, None))

    def test_group_geo_zones_change_invalidates_members(self):
        user, group, _ = create_user_with_group(
            email="member@example.com", group_name="GeoGroup"
        )
        region = GeoRegion.objects.create(
            name="Region2",
            name_normalized="region2",
            insee_code="cache-test-region-2",
            surface_km2=1,
        )
        key_before = get_user_geo_cache_key(user.id, None)

        with self.captureOnCommitCallbacks(execute=True):
            group.geo_zones.add(region)

        self.assertNotEqual(key_before, get_user_geo_cache_key(user.id, None))


class UserServiceCacheInvalidationTests(TestCase):
    """bulk_create/bulk_update bypass post_save, so the user service must
    invalidate explicitly when (re)assigning group memberships."""

    def test_bulk_group_assignment_invalidates_user_cache(self):
        requesting_user = create_super_admin()
        group = create_user_group(name="SvcGroup")
        user = create_regular_user()
        key_before = get_user_geo_cache_key(user.id, None)

        with self.captureOnCommitCallbacks(execute=True):
            UserService._update_user_groups(
                user=user,
                user_user_groups=[
                    {
                        "user_group_uuid": group.uuid,
                        "user_group_rights": [UserGroupRight.READ],
                    }
                ],
                requesting_user=requesting_user,
            )

        self.assertNotEqual(key_before, get_user_geo_cache_key(user.id, None))


class CountInvalidationSignalTests(TestCase):
    """Count-relevant writes beyond Detection/DetectionData/Parcel must also bump
    the count version: single DetectionObject saves and custom-zone associations."""

    def test_detection_object_save_invalidates_count(self):
        version_before = get_count_cache_version()
        with self.captureOnCommitCallbacks(execute=True):
            create_detection_object(object_type=create_object_type(name="CountSigType"))
        self.assertNotEqual(version_before, get_count_cache_version())

    def test_custom_zone_association_invalidates_count(self):
        detection_object = create_detection_object(
            object_type=create_object_type(name="CountSigType2")
        )
        zone = GeoCustomZone.objects.create(
            name="CountSigZone",
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        )
        version_before = get_count_cache_version()
        with self.captureOnCommitCallbacks(execute=True):
            detection_object.geo_custom_zones.add(zone)
        self.assertNotEqual(version_before, get_count_cache_version())
