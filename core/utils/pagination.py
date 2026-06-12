import hashlib

from django.db.models import QuerySet
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from core.utils.cache import (
    COUNT_CACHE_TTL,
    get_count_cache_version,
    get_or_compute,
)


def generate_query_cache_key(queryset, scope=None):
    """Cache key for a queryset's COUNT.

    Combines the model, the full SQL (which inlines the filters), the global count
    version (so any detection/parcel write invalidates it), and an optional ``scope``
    string. The scope is the requesting user, so two users whose querysets render to
    coincidentally-identical SQL can never share a cached count — isolation is
    explicit here, not dependent on every permission predicate being inlined.
    """
    query_hash = hashlib.md5(str(queryset.query).encode()).hexdigest()
    model_name = queryset.model._meta.model_name
    version = get_count_cache_version()
    scope_part = f"{scope}_" if scope else ""
    return f"query_count_{model_name}_{scope_part}{version}_{query_hash}"


class CachedCountLimitOffsetPagination(LimitOffsetPagination):
    """LimitOffsetPagination that caches the (expensive) total COUNT per query.

    The count is version-invalidated on every count-relevant write (see
    core.utils.cache.invalidate_count_caches), so cache_timeout is only a backstop.
    """

    use_distinct = True
    cache_timeout = COUNT_CACHE_TTL

    def get_count(self, queryset):
        if not isinstance(queryset, QuerySet):
            return len(queryset)

        cache_key = generate_query_cache_key(queryset, scope=self._count_cache_scope())
        return get_or_compute(
            cache_key, lambda: self._compute_count(queryset), self.cache_timeout
        )

    def _compute_count(self, queryset):
        if self.use_distinct:
            return queryset.distinct().count()
        return super().get_count(queryset)

    def _count_cache_scope(self):
        """Scope the count cache to the requesting user so identical SQL across users
        never collides. Falls back to None (still correct via the inlined SQL)."""
        request = getattr(self, "request", None)
        user_id = getattr(getattr(request, "user", None), "id", None)
        return f"u{user_id}" if user_id else None

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )
