from django.db.models import QuerySet
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
import hashlib

from core.utils.cache import (
    COUNT_CACHE_TTL,
    get_count_cache_version,
    safe_cache_get,
    safe_cache_set,
)


def generate_query_cache_key(queryset):
    """
    Generate a unique cache key based on the query.
    This handles different filter conditions by including them in the key.

    A global count version is folded in so that detection/parcel writes (which
    bump the version) cannot serve a stale count — the cached SQL string alone is
    data-agnostic and would otherwise stay valid for the whole TTL.
    """
    query = str(queryset.query)
    # Create a hash of the query to keep the key a reasonable length
    query_hash = hashlib.md5(query.encode()).hexdigest()
    model_name = queryset.model._meta.model_name
    version = get_count_cache_version()
    return f"query_count_{model_name}_{version}_{query_hash}"


class CachedCountLimitOffsetPagination(LimitOffsetPagination):
    use_distinct = True

    """
    A LimitOffsetPagination class that caches counts for filtered querysets.
    """

    # Backstop TTL; the count is also version-invalidated on data writes.
    cache_timeout = COUNT_CACHE_TTL

    def get_count(self, queryset):
        """
        Determine the total number of items in the object list.
        Uses cached value if available, otherwise calculates and caches the count.
        """
        if not isinstance(queryset, QuerySet):
            return len(queryset)

        # Generate a unique cache key for this specific query
        cache_key = generate_query_cache_key(queryset)

        # Try to get count from cache
        count = safe_cache_get(cache_key)

        if count is None:
            # Cache miss, calculate the actual count
            if self.use_distinct:
                count = queryset.distinct().count()
            else:
                count = super().get_count(queryset)
            # Store in cache
            safe_cache_set(cache_key, count, self.cache_timeout)

        return count

    def get_paginated_response(self, data):
        """
        Returns a paginated response with cache info.
        """
        return Response(
            {
                "count": self.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )
