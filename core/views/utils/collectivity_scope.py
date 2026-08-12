"""Shared collectivity scoping for the geo list endpoints.

`geo/commune`, `geo/epci`, `geo/department` and `geo/region` all answer the same
question — "which rows of MY level relate to what the caller can access?" — and the
relation runs both ways: a department user sees that department's communes, a commune
user sees the department containing it. `ZONE_RELATION_LOOKUP` holds every direction,
so a new level is one table entry rather than a new branch in four filters.
"""

from django.db.models import Q

from core.constants.collectivity import ZONE_RELATION_LOOKUP
from core.models.geo_zone import GeoZoneType


def scope_by_collectivity(queryset, request, level: GeoZoneType):
    # Imported here: core.permissions.user pulls in the repository layer, which imports
    # views in turn.
    from core.permissions.user import UserPermission

    collectivity_filter = UserPermission.from_request(request).get_collectivity_filter()

    if not collectivity_filter:
        return queryset

    q = Q()
    for filter_level, ids in collectivity_filter.levels():
        q |= Q(**{f"{ZONE_RELATION_LOOKUP[(level, filter_level)]}__in": ids})

    if not q:
        return queryset.none()

    # The lookups above traverse multi-valued relations (a region joins its communes),
    # so without this a region comes back once per matching commune.
    return queryset.filter(q).distinct()
