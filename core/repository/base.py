from dataclasses import dataclass
from datetime import datetime
from typing import Generic, List, Optional, Tuple, TypeVar
from django.db.models import Model, QuerySet
from enum import Enum
from common.models.uuid import UuidModelMixin
from django.db.models import Q

T_MODEL = TypeVar("T_MODEL", bound=Model)
T_UUID_MODEL = TypeVar("T_UUID_MODEL", bound=UuidModelMixin)


class BaseRepository(
    Generic[T_MODEL],
):
    queryset: QuerySet[T_MODEL]
    q: Q

    def __init__(self, queryset: Optional[QuerySet[T_MODEL]]):
        self.queryset = queryset
        self.q = Q()

    def _order_by(self, order_bys: Optional[List[str]] = None, *args, **kwargs):
        if order_bys is not None:
            self.queryset = self.queryset.order_by(order_bys)

    def _filter(self, *args, **kwargs):
        raise NotImplementedError(
            f"Filter method not implemented for {self.__class__.__name__}"
        )

    def list_(self, *args, **kwargs):
        self._filter(*args, **kwargs)
        self._order_by(*args, **kwargs)

        return self.queryset.all()


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


class TimestampedBaseRepositoryMixin(
    Generic[T_UUID_MODEL],
):
    @staticmethod
    def _filter_timestamped(
        queryset: QuerySet[T_MODEL],
        q: Q,
        filter_created_at: Optional[DateRepoFilter] = None,
        filter_updated_at: Optional[DateRepoFilter] = None,
    ) -> Tuple[QuerySet[T_MODEL], List[Q]]:
        if filter_created_at is not None:
            q_ = Q(
                **{
                    f"created_at__{filter_created_at.lookup.value}": filter_created_at.date
                }
            )
            queryset = queryset.filter(q_)
            q &= q_

        if filter_updated_at is not None:
            q_ = Q(
                **{
                    f"updated_at__{filter_updated_at.lookup.value}": filter_updated_at.date
                }
            )
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q


class UuidBaseRepositoryMixin(
    Generic[T_UUID_MODEL],
):
    @staticmethod
    def _filter_uuid(
        queryset: QuerySet[T_MODEL],
        q: Q,
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
    ) -> Tuple[QuerySet[T_MODEL], List[Q]]:
        if filter_uuid_in is not None:
            q_ = Q(uuid__in=filter_uuid_in)
            queryset = queryset.filter(q_)
            q &= q_

        if filter_uuid_notin:
            q_ = ~Q(uuid__in=filter_uuid_notin)
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q
