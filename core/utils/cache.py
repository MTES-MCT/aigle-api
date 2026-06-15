"""Versioned, fail-open application cache (Redis in prod, LocMemCache in tests).

Single source of truth for the app's derived caches, all of which back the detection
map and lists — so correctness and per-user isolation are critical.

It uses *version-keyed* invalidation: a monotonic counter is embedded in each cache
key, and "invalidating" a group of entries means bumping its counter so the keys the
next request builds no longer match the stale entries (which then expire by TTL).
This gives O(1) group invalidation without scanning/deleting keys, and is
transaction-safe because every bump runs inside transaction.on_commit (see callers).
Trade-off of on_commit: the bump fires just AFTER the writer's commit, so for a
single-digit-millisecond window another worker can observe the newly committed rows
yet still resolve the pre-bump version and serve a slightly stale count. This is the
deliberate, correct choice — invalidating before commit would instead let a reader
re-cache not-yet-committed data under the new version, which is worse.

Caches and their invalidation contract
--------------------------------------
1. user-geo union  — UserPermission.get_accessible_geometry; key get_user_geo_cache_key.
   Invalidated by: the user's version (group-membership change), the group's version
   (group.geo_zones change), or the global geo version (geo-zone geometry re-import).
2. tileset filter  — TileSetPermission._get_cached_tilesets; key get_tileset_filter_cache_key.
   Invalidated by: the user's/group's version (accessible-zone change) or the global
   tileset version (TileSet save/delete or TileSet.geo_zones change).
3. pagination count — CachedCountLimitOffsetPagination; key folds in get_count_cache_version().
   Invalidated by: the global count version, bumped on any write to Detection,
   DetectionData, DetectionObject or Parcel, or a DetectionObject.geo_custom_zones m2m
   change.
4. deployed-data overview — DeployedDataService (SUPER_ADMIN dashboard); keys fold in
   get_deployed_data_cache_version(). Invalidated ONLY by invalidate_deployed_data_cache(),
   called out-of-band by `warm_deployed_data_cache` after a detection/parcel import — NOT
   on every write (this is a slow-moving figure that tolerates bounded staleness; folding
   in the per-write count version would defeat the cache). Unlike 1-3 this is not
   per-user.

Signal wiring lives in core/signals.py. Bulk writes (bulk_create / bulk_update /
*_with_history) and raw SQL do NOT emit post_save/post_delete, so every such write
site MUST call the matching invalidate_*() explicitly (grep the invalidate_* names to
see them).

Fail-open contract
------------------
Redis sits in the request path and in write-path signals, so a backend outage must
degrade to "recompute" — never 500 a read, block a write, or serve corrupt data.
Every access goes through safe_cache_get / safe_cache_set / get_or_compute /
_increment_version, which swallow and log backend errors; with the version counters
unreachable, every key resolves to version 1 consistently, so callers just recompute.
"""

import logging
import os
from typing import Callable, Optional, TypeVar

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Namespace + schema version for every key. Bump CACHE_SCHEMA_VERSION to force a
# one-time cold start of the whole cache (e.g. if a cached value's pickled shape
# changes); old keys are simply orphaned and expire by TTL.
CACHE_SCHEMA_VERSION = 1
_NS = f"aigle:v{CACHE_SCHEMA_VERSION}"

# TTLs in seconds, overridable via env so they can be tuned on the server (edit .env,
# restart gunicorn) without a code deploy. All caches are invalidated on every
# relevant write, so the TTL is only an upper bound on staleness, not the primary
# mechanism. The count cache is bumped on every detection write, so under active load
# it rarely lives to its TTL regardless — a high value mainly helps quiet windows.
USER_GEO_CACHE_TTL = int(os.environ.get("USER_GEO_CACHE_TTL", 6 * 60 * 60))  # 6h
TILESET_FILTER_CACHE_TTL = int(
    os.environ.get("TILESET_FILTER_CACHE_TTL", 24 * 60 * 60)
)  # 24h
COUNT_CACHE_TTL = int(os.environ.get("COUNT_CACHE_TTL", 2 * 60 * 60))  # 2h
VERSION_TTL = None  # version counters anchor invalidation — must never expire

T = TypeVar("T")


# --- Fail-open primitives -------------------------------------------------------


def safe_cache_get(key: str, default=None):
    try:
        return cache.get(key, default)
    except Exception:
        logger.exception("Cache get failed for key %s", key)
        return default


def safe_cache_set(key: str, value, timeout) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.exception("Cache set failed for key %s", key)


def get_or_compute(
    key: str, compute: Callable[[], Optional[T]], timeout
) -> Optional[T]:
    """Return the cached value at ``key``; on a miss, call ``compute`` and cache it.

    A ``None`` result is treated as "do not cache", so callers can skip caching empty
    results (e.g. a user with no accessible geometry) and recompute cheaply instead.
    Fail-open: if the backend errors, the read behaves as a miss and the write is a
    no-op, so this degrades to always calling ``compute`` — never raising.
    """
    cached = safe_cache_get(key)
    if cached is not None:
        return cached
    value = compute()
    if value is not None:
        safe_cache_set(key, value, timeout)
    return value


# --- Version counters (the invalidation mechanism) ------------------------------


def _get_version(version_key: str) -> int:
    version = safe_cache_get(version_key)
    if version is None:
        # SETNX init (cache.add only writes if absent) so a reader can never clobber a
        # concurrent _increment_version by writing 1 over an already-bumped value —
        # the cold-start / post-Redis-restart lost-update race. Re-read to pick up
        # whichever value actually won.
        try:
            cache.add(version_key, 1, timeout=VERSION_TTL)
            version = cache.get(version_key)
        except Exception:
            logger.exception("Cache add failed for key %s", version_key)
        if version is None:
            version = 1
    return version


def _increment_version(version_key: str) -> None:
    try:
        # add() is a no-op if the key exists; it guarantees incr() has a base so we
        # never fall back to an unconditional set(2) that could clobber a higher,
        # concurrently-set version. Both add and incr are atomic in Redis.
        cache.add(version_key, 0, timeout=VERSION_TTL)
        cache.incr(version_key)
    except Exception:
        # Backend unavailable: fail open. Staleness is bounded by the data TTLs.
        logger.exception("Cache incr failed for key %s", version_key)


def _user_version_key(user_id: int) -> str:
    return f"{_NS}:ver:user:{user_id}"


def _group_version_key(group_id: int) -> str:
    return f"{_NS}:ver:group:{group_id}"


# Global version counters, each bumped by one invalidate_*() below.
_GEO_VERSION_KEY = f"{_NS}:ver:geo"
_TILESET_VERSION_KEY = f"{_NS}:ver:tileset"
_COUNT_VERSION_KEY = f"{_NS}:ver:count"
_DEPLOYED_DATA_VERSION_KEY = f"{_NS}:ver:deployed_data"


# --- Cache-key builders ---------------------------------------------------------


def _scope_version(user_id: int, scoped_user_group_id) -> int:
    """Version that scopes a per-user cache: the group's when impersonating a group,
    else the user's own. invalidate_caches_for_group bumps both, so either is safe."""
    if scoped_user_group_id:
        return _get_version(_group_version_key(scoped_user_group_id))
    return _get_version(_user_version_key(user_id))


def get_user_geo_cache_key(user_id: int, scoped_user_group_id) -> str:
    geo_version = _get_version(_GEO_VERSION_KEY)
    version = _scope_version(user_id, scoped_user_group_id)
    group_part = scoped_user_group_id or 0
    return f"{_NS}:user_geo:{geo_version}:{version}:{user_id}:{group_part}"


def get_tileset_filter_cache_key(
    user_id: int, scoped_user_group_id, filter_hash: str
) -> str:
    version = _scope_version(user_id, scoped_user_group_id)
    ts_version = _get_version(_TILESET_VERSION_KEY)
    group_part = scoped_user_group_id or 0
    return (
        f"{_NS}:ts_filter:{version}:{ts_version}:{user_id}:{group_part}:{filter_hash}"
    )


def get_count_cache_version() -> int:
    return _get_version(_COUNT_VERSION_KEY)


def get_deployed_data_cache_version() -> int:
    return _get_version(_DEPLOYED_DATA_VERSION_KEY)


# --- Invalidation API (call these after the matching write) ---------------------


def invalidate_caches_for_user(user_id: int) -> None:
    """A user's group membership changed -> their geo-union and tileset caches."""
    _increment_version(_user_version_key(user_id))
    logger.info("Invalidated caches for user %s", user_id)


def invalidate_caches_for_group(group_id: int) -> None:
    """A group's geo_zones changed -> the group's and every member's caches."""
    from core.models.user_group import UserUserGroup

    _increment_version(_group_version_key(group_id))

    try:
        user_ids = list(
            UserUserGroup.objects.filter(user_group_id=group_id).values_list(
                "user_id", flat=True
            )
        )
    except Exception:
        # Runs in transaction.on_commit, after the write has already committed, so a
        # transient DB error here must not 500 the request. Members fall back to TTL.
        logger.exception(
            "Failed to load members for group %s cache invalidation", group_id
        )
        return

    for uid in user_ids:
        _increment_version(_user_version_key(uid))

    logger.info(
        "Invalidated caches for group %s and %d member(s)", group_id, len(user_ids)
    )


def invalidate_user_geo_caches() -> None:
    """A geo-zone geometry changed -> every user's geo-union cache."""
    _increment_version(_GEO_VERSION_KEY)
    logger.info("Invalidated all user geo caches")


def invalidate_tileset_filter_caches() -> None:
    """A TileSet or its geo_zones changed -> every user's tileset-filter cache."""
    _increment_version(_TILESET_VERSION_KEY)
    logger.info("Invalidated all tileset filter caches")


def invalidate_count_caches() -> None:
    """A count-relevant row (Detection/DetectionData/DetectionObject/Parcel or a
    detection's custom-zone link) changed -> every cached pagination count."""
    _increment_version(_COUNT_VERSION_KEY)
    logger.info("Invalidated all pagination count caches")


def invalidate_deployed_data_cache() -> None:
    """Bump the deployed-data version so the SUPER_ADMIN "deployed data" overview (the
    summary list AND every per-department detail) is orphaned and recomputed on next
    access. Called out-of-band by `warm_deployed_data_cache` after a detection/parcel
    import — deliberately NOT on every write, since this is a slow-moving
    deployment-status overview that tolerates bounded staleness (the data TTL is the
    upper bound). See core/services/deployed_data.py."""
    _increment_version(_DEPLOYED_DATA_VERSION_KEY)
    logger.info("Invalidated deployed-data cache")
