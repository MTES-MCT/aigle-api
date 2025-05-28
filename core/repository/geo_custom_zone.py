from typing import List, Optional
from core.models.geo_custom_zone import GeoCustomZone
from core.repository.base import (
    BaseRepository,
    DateRepoFilter,
    TimestampedBaseRepositoryMixin,
    UuidBaseRepositoryMixin,
)
from django.db.models import QuerySet


class GeoCustomZoneRepository(
    BaseRepository[GeoCustomZone],
    TimestampedBaseRepositoryMixin[GeoCustomZone],
    UuidBaseRepositoryMixin[GeoCustomZone],
):
    def __init__(self, initial_queryset: Optional[QuerySet[GeoCustomZone]] = None):
        self.model = GeoCustomZone
        self.initial_queryset = (
            initial_queryset if initial_queryset is not None else self.model.objects
        )

    def filter_(
        self,
        queryset: QuerySet[GeoCustomZone],
        filter_created_at: Optional[DateRepoFilter] = None,
        filter_updated_at: Optional[DateRepoFilter] = None,
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
        order_bys: Optional[List[str]] = None,
        *args,
        **kwargs,
    ) -> QuerySet[GeoCustomZone]:
        # mixin filters

        queryset = self._filter_timestamped(
            queryset=queryset,
            filter_created_at=filter_created_at,
            filter_updated_at=filter_updated_at,
        )
        queryset = self._filter_uuid(
            queryset=queryset,
            filter_uuid_in=filter_uuid_in,
            filter_uuid_notin=filter_uuid_notin,
        )

        queryset = self.order_by(queryset=queryset, order_bys=order_bys)

        return queryset
