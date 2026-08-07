from dataclasses import dataclass
from datetime import datetime
from typing import Generic, List, Optional, TypeVar
from django.db.models import Model, QuerySet
from enum import Enum
from common.models.uuid import UuidModelMixin
from django.db.models import Q


T_MODEL = TypeVar("T_MODEL", bound=Model)
T_UUID_MODEL = TypeVar("T_UUID_MODEL", bound=UuidModelMixin)


class BaseRepository(
    Generic[T_MODEL],
):
    initial_queryset: QuerySet[T_MODEL]
    model: T_MODEL

    def __init__(self, initial_queryset: Optional[QuerySet[T_MODEL]] = None):
        if initial_queryset is not None:
            self.initial_queryset = initial_queryset
        else:
            self.initial_queryset = self.model.objects

    def order_by(
        self,
        queryset: QuerySet[T_MODEL],
        order_bys: Optional[List[str]] = None,
        *args,
        **kwargs,
    ) -> QuerySet[T_MODEL]:
        if order_bys is not None:
            queryset = queryset.order_by(*order_bys)

        return queryset

    def filter_(
        self, queryset: QuerySet[T_MODEL], *args, **kwargs
    ) -> QuerySet[T_MODEL]:
        raise NotImplementedError(
            f"Filter method not implemented for {self.__class__.__name__}"
        )

    def list_(self, *args, **kwargs):
        queryset = self.initial_queryset

        queryset = self.filter_(queryset=queryset, *args, **kwargs)
        queryset = self.order_by(queryset=queryset, *args, **kwargs)

        return queryset.distinct()

    def get(self, *args, **kwargs):
        queryset = self.initial_queryset

        queryset = self.filter_(queryset=queryset, *args, **kwargs)
        queryset = self.order_by(queryset=queryset, *args, **kwargs)

        return queryset.first()


class RepoFilterLookup(Enum):
    GTE = "gte"
    GT = "gt"
    LTE = "lte"
    LT = "lt"


@dataclass
class NumberRepoFilter:
    lookup: RepoFilterLookup
    number: float


@dataclass
class DateRepoFilter:
    lookup: RepoFilterLookup
    date: datetime


@dataclass
class CollectivityRepoFilter:
    commune_ids: Optional[List[int]] = None
    epci_ids: Optional[List[int]] = None
    department_ids: Optional[List[int]] = None
    region_ids: Optional[List[int]] = None

    def is_empty(self) -> bool:
        return all(ids is None for _, ids in self._all_levels())

    def _all_levels(self):
        from core.constants.collectivity import COLLECTIVITY_LEVELS

        return [
            (level, getattr(self, f"{level.lower()}_ids"))
            for level in COLLECTIVITY_LEVELS
        ]

    def levels(self):
        """(GeoZoneType, ids) for the levels this filter actually restricts on."""
        return [(level, ids) for level, ids in self._all_levels() if ids]


def collectivity_q(
    filter_collectivities: CollectivityRepoFilter, commune_prefix: str = ""
) -> Q:
    """Rows whose commune — reached through `commune_prefix` — belongs to any of the
    filtered collectivities, walking foreign keys only (never geometry).

    Fails closed: a filter naming no collectivity at all matches nothing, so a caller
    that forgot to guard `is_empty()` hides rows instead of exposing them.
    """
    from core.constants.collectivity import COMMUNE_LOOKUP_BY_LEVEL

    levels = filter_collectivities.levels()
    if not levels:
        return Q(pk__in=[])

    q = Q()
    for level, ids in levels:
        q |= Q(**{f"{commune_prefix}{COMMUNE_LOOKUP_BY_LEVEL[level]}__in": ids})
    return q


class TimestampedBaseRepositoryMixin(
    Generic[T_UUID_MODEL],
):
    @staticmethod
    def _filter_timestamped(
        queryset: QuerySet[T_MODEL],
        filter_created_at: Optional[DateRepoFilter] = None,
        filter_updated_at: Optional[DateRepoFilter] = None,
    ) -> List[Q]:
        if filter_created_at is not None:
            q = Q(
                **{
                    f"created_at__{filter_created_at.lookup.value}": filter_created_at.date
                }
            )
            queryset = queryset.filter(q)

        if filter_updated_at is not None:
            q = Q(
                **{
                    f"updated_at__{filter_updated_at.lookup.value}": filter_updated_at.date
                }
            )
            queryset = queryset.filter(q)

        return queryset


class UuidBaseRepositoryMixin(
    Generic[T_UUID_MODEL],
):
    @staticmethod
    def _filter_uuid(
        queryset: QuerySet[T_MODEL],
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
    ) -> List[Q]:
        if filter_uuid_in is not None:
            q = Q(uuid__in=filter_uuid_in)
            queryset = queryset.filter(q)

        if filter_uuid_notin:
            q = ~Q(uuid__in=filter_uuid_notin)
            queryset = queryset.filter(q)

        return queryset
