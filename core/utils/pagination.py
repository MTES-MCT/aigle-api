from rest_framework.pagination import LimitOffsetPagination
from core.utils.postgis import estimate_count
from rest_framework.response import Response


class EstimatedCountLimitOffsetPagination(LimitOffsetPagination):
    """
    A LimitOffsetPagination class that uses estimated counts for faster pagination.
    """

    def __init__(self):
        super().__init__()
        self._count = None
        self._is_estimated = True

    def get_count(self, queryset):
        """
        Determine the total number of items in the object list.
        Uses an estimate from PostgreSQL's statistics instead of an exact count.
        """
        if self._count is None:
            self._count = estimate_count(queryset)
        return self._count

    def get_paginated_response(self, data):
        """
        Adds 'is_estimated' flag to the response.
        """
        return Response(
            {
                "count": self.count,
                "is_estimated": self._is_estimated,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )
