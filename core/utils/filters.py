from django_filters import (
    BaseInFilter,
    UUIDFilter,
    ChoiceFilter,
    OrderingFilter,
)


class UuidInFilter(BaseInFilter, UUIDFilter):
    pass


class ChoiceInFilter(BaseInFilter, ChoiceFilter):
    pass


class StableOrderingFilter(OrderingFilter):
    def filter(self, qs, value):
        qs = super().filter(qs, value)
        # rows with equal sort values must not swap between pages
        return qs.order_by(*qs.query.order_by, "id") if value else qs
