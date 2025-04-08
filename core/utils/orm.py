from django.db import models


class ListValuesListIterable(models.query.ValuesListIterable):
    def __iter__(self):
        for row in super().__iter__():
            yield list(row)


def get_list_values_list(queryset, *fields, **kwargs):
    clone = queryset.values_list(*fields, **kwargs)
    clone._iterable_class = ListValuesListIterable
    return clone
