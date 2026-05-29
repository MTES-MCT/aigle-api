import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

USER_GEO_CACHE_TTL = 300  # 5 minutes
TILESET_FILTER_CACHE_TTL = 1800  # 30 minutes
# Backstop only: pagination counts are version-invalidated on detection/parcel
# writes (see invalidate_count_caches). The TTL bounds staleness for writes that
# bypass signals, e.g. bulk_create during imports.
COUNT_CACHE_TTL = 600  # 10 minutes
VERSION_TTL = None  # versions never expire on their own


# --- Fail-open cache primitives -------------------------------------------------
# Redis now sits in the request/response path AND in write-path invalidation
# signals. A cache backend outage must degrade performance, not take the API down
# (reads 500, writes blocked). Every cache access goes through these wrappers, so a
# backend error is logged and swallowed: a read behaves as a miss, a write/version
# bump becomes a no-op. With versions unreachable, every key resolves to version 1
# consistently, so callers simply recompute — never serve corrupt data.


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


def _get_version(version_key: str) -> int:
    version = safe_cache_get(version_key)
    if version is None:
        version = 1
        safe_cache_set(version_key, version, timeout=VERSION_TTL)
    return version


def _increment_version(version_key: str):
    try:
        cache.incr(version_key)
    except ValueError:
        # Key not initialised yet — jump past the implicit version 1.
        safe_cache_set(version_key, 2, timeout=VERSION_TTL)
    except Exception:
        # Backend unavailable: fail open. Staleness is bounded by the data TTLs.
        logger.exception("Cache incr failed for key %s", version_key)


def _user_version_key(user_id: int) -> str:
    return f"aigle:uv:{user_id}"


def _group_version_key(group_id: int) -> str:
    return f"aigle:gv:{group_id}"


TILESET_GLOBAL_VERSION_KEY = "aigle:tsv"
# Bumped whenever any geo zone geometry changes. The per-user geo union is built
# from GeoZone.geometry, but we cannot cheaply know which users a given zone edit
# affects, so a single global version invalidates every user/group geo-union cache
# at once. Note: bulk geo imports bypass model signals — they must call
# invalidate_user_geo_caches() explicitly or rely on USER_GEO_CACHE_TTL.
USER_GEO_GLOBAL_VERSION_KEY = "aigle:ugv"
# Bumped on detection/parcel writes so cached pagination counts cannot go stale
# beyond the next write. COUNT_CACHE_TTL is only a backstop for signal-less writes.
COUNT_GLOBAL_VERSION_KEY = "aigle:cv"


def get_user_geo_cache_key(user_id: int, scoped_user_group_id) -> str:
    geo_version = _get_version(USER_GEO_GLOBAL_VERSION_KEY)
    if scoped_user_group_id:
        version = _get_version(_group_version_key(scoped_user_group_id))
    else:
        version = _get_version(_user_version_key(user_id))
    group_part = scoped_user_group_id or 0
    return f"aigle:user_geo:{geo_version}:{version}:{user_id}:{group_part}"


def get_tileset_filter_cache_key(
    user_id: int, scoped_user_group_id, filter_hash: str
) -> str:
    if scoped_user_group_id:
        user_version = _get_version(_group_version_key(scoped_user_group_id))
    else:
        user_version = _get_version(_user_version_key(user_id))
    ts_version = _get_version(TILESET_GLOBAL_VERSION_KEY)
    group_part = scoped_user_group_id or 0
    return f"aigle:ts_filter:{user_version}:{ts_version}:{user_id}:{group_part}:{filter_hash}"


def get_count_cache_version() -> int:
    return _get_version(COUNT_GLOBAL_VERSION_KEY)


def invalidate_caches_for_user(user_id: int):
    _increment_version(_user_version_key(user_id))
    logger.info("Invalidated caches for user %s", user_id)


def invalidate_caches_for_group(group_id: int):
    from core.models.user_group import UserUserGroup

    _increment_version(_group_version_key(group_id))

    user_ids = UserUserGroup.objects.filter(user_group_id=group_id).values_list(
        "user_id", flat=True
    )
    for uid in user_ids:
        _increment_version(_user_version_key(uid))

    logger.info(
        "Invalidated caches for group %s and %d member(s)", group_id, len(user_ids)
    )


def invalidate_tileset_filter_caches():
    _increment_version(TILESET_GLOBAL_VERSION_KEY)
    logger.info("Invalidated all tileset filter caches")


def invalidate_user_geo_caches():
    _increment_version(USER_GEO_GLOBAL_VERSION_KEY)
    logger.info("Invalidated all user geo caches")


def invalidate_count_caches():
    _increment_version(COUNT_GLOBAL_VERSION_KEY)
    logger.info("Invalidated all pagination count caches")
