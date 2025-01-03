from datetime import datetime
from typing import Generic, List, Optional, TypeVar
from django.db.models import Model, QuerySet
from enum import Enum
from common.models.uuid import UuidModelMixin

T_MODEL = TypeVar("T_MODEL", bound=Model)
T_UUID_MODEL = TypeVar("T_UUID_MODEL", bound=UuidModelMixin)


class BaseRepository(
    Generic[T_MODEL],
):
    queryset: QuerySet[T_MODEL]

    def __init__(self, queryset: Optional[QuerySet[T_MODEL]]):
        self.queryset = queryset or T_MODEL.objects

    def _order_by(self, order_bys: Optional[List[str]] = None, *args, **kwargs):
        if order_bys is not None:
            self.queryset = self.queryset.order_by(order_bys)

    def _filter(self, *args, **kwargs):
        raise NotImplementedError(
            f"Filter method not implemented for {self.__class__.__name__}"
        )

    def list(self, *args, **kwargs):
        self._filter(*args, **kwargs)
        self._order_by(*args, **kwargs)

        return self.queryset.all()


class FilterLookup(Enum):
    GTE = "gte"
    GT = "gt"
    LTE = "lte"
    LT = "lt"


class NumberFilter:
    lookup: FilterLookup
    number: float


class DateFilter:
    lookup: FilterLookup
    date: datetime


class TimestampedBaseRepositoryMixin(
    Generic[T_UUID_MODEL],
):
    @staticmethod
    def _filter_timestamped(
        queryset: QuerySet[T_MODEL],
        filter_created_at: Optional[DateFilter] = None,
        filter_updated_at: Optional[DateFilter] = None,
    ) -> QuerySet[T_MODEL]:
        if filter_created_at is not None:
            queryset = queryset.filter(
                **{
                    f"created_at__{filter_created_at.lookup.value}": filter_created_at.date
                }
            )

        if filter_updated_at is not None:
            queryset = queryset.filter(
                **{
                    f"updated_at__{filter_updated_at.lookup.value}": filter_updated_at.date
                }
            )

        return queryset


class UuidBaseRepositoryMixin(
    Generic[T_UUID_MODEL],
):
    @staticmethod
    def _filter_uuid(
        queryset: QuerySet[T_MODEL],
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
    ) -> QuerySet[T_MODEL]:
        if filter_uuid_in is not None:
            queryset = queryset.filter(uuid__in=filter_uuid_in)

        if filter_uuid_notin:
            queryset = queryset.exclude(uuid__in=filter_uuid_notin)

        return queryset
