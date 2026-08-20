from django.db.models import BooleanField, Func


class ArrayHasUniqueValues(Func):
    """True when the array holds no duplicated element.

    Postgres has no set type and forbids subqueries inside CHECK constraints, so the
    de-duplication lives in an IMMUTABLE SQL function created by core migration 0133.
    This wrapper is what lets a model declare the constraint in its Meta.
    """

    function = "array_has_unique_values"
    output_field = BooleanField()
