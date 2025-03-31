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
        if initial_queryset:
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
    department_ids: Optional[List[int]] = None
    region_ids: Optional[List[int]] = None

    def is_empty(self) -> bool:
        return (
            self.commune_ids is None
            and self.department_ids is None
            and self.region_ids is None
        )


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
