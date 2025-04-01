from django.core.cache import cache
from django.db.models import QuerySet
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
import hashlib


def generate_query_cache_key(queryset):
    """
    Generate a unique cache key based on the query.
    This handles different filter conditions by including them in the key.
    """
    query = str(queryset.query)
    # Create a hash of the query to keep the key a reasonable length
    query_hash = hashlib.md5(query.encode()).hexdigest()
    model_name = queryset.model._meta.model_name
    return f"query_count_{model_name}_{query_hash}"


class CachedCountLimitOffsetPagination(LimitOffsetPagination):
    """
    A LimitOffsetPagination class that caches counts for filtered querysets.
    """

    # How long to cache the count (in seconds), adjust as needed
    cache_timeout = 60 * 60  # 1 hour

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
        count = cache.get(cache_key)

        if count is None:
            # Cache miss, calculate the actual count
            count = super().get_count(queryset)
            # Store in cache
            cache.set(cache_key, count, self.cache_timeout)

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
