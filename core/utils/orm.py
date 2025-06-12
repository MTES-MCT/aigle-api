from typing import Any
from django.db import models


class ListValuesListIterable(models.query.ValuesListIterable):
    def __iter__(self):
        for row in super().__iter__():
            yield list(row)


def get_list_values_list(
    queryset: models.QuerySet, *fields: str, **kwargs: Any
) -> models.QuerySet:
    clone = queryset.values_list(*fields, **kwargs)
    clone._iterable_class = ListValuesListIterable
    return clone
