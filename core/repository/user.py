from typing import List, Optional
from core.models.user import User
from core.repository.base import (
    BaseRepository,
    DateRepoFilter,
    TimestampedBaseRepositoryMixin,
    UuidBaseRepositoryMixin,
)
from django.db.models import QuerySet


class UserRepository(
    BaseRepository[User],
    TimestampedBaseRepositoryMixin[User],
    UuidBaseRepositoryMixin[User],
):
    def __init__(self, initial_queryset: Optional[QuerySet[User]] = None):
        self.model = User
        super().__init__(initial_queryset=initial_queryset)

    def _filter(
        self,
        queryset: QuerySet[User],
        filter_created_at: Optional[DateRepoFilter] = None,
        filter_updated_at: Optional[DateRepoFilter] = None,
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
        order_bys: Optional[List[str]] = None,
        *args,
        **kwargs,
    ) -> QuerySet[User]:
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

        queryset = self._order_by(queryset=queryset, order_bys=order_bys)

        return queryset
