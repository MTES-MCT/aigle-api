from typing import TYPE_CHECKING, Iterable

from django.db import connection

from core.models.path_validation_progress import PathValidationProgress
from core.utils.bitmask import indices_to_mask

if TYPE_CHECKING:
    from core.models.user import User


# One statement, so concurrent tabs and first writes need no transaction or row lock.
# ~(-1 << n) is the full mask of n items ((1 << n) - 1 overflows int4 at n = 31); | & << share one precedence.
_UPSERT_SQL = """
    INSERT INTO core_pathvalidationprogress AS p (
        user_id, updated_at, completed_at, checked_items, item_count
    )
    VALUES (
        %(user_id)s,
        now(),
        CASE WHEN %(check)s = ~(-1 << %(item_count)s) THEN now() END,
        %(check)s,
        %(item_count)s
    )
    ON CONFLICT (user_id) DO UPDATE SET
        checked_items = (p.checked_items | EXCLUDED.checked_items) & ~%(uncheck)s,
        item_count = GREATEST(p.item_count, EXCLUDED.item_count),
        completed_at = CASE
            WHEN ((p.checked_items | EXCLUDED.checked_items) & ~%(uncheck)s)
                <> ~(-1 << GREATEST(p.item_count, EXCLUDED.item_count))
                THEN NULL
            WHEN p.checked_items = ~(-1 << GREATEST(p.item_count, EXCLUDED.item_count))
                THEN COALESCE(p.completed_at, now())
            ELSE now()
        END,
        updated_at = now()
    RETURNING checked_items, item_count, completed_at, updated_at
"""


class PathValidationProgressService:
    @staticmethod
    def get(user: "User") -> PathValidationProgress:
        progress = PathValidationProgress.objects.filter(user_id=user.id).first()
        return progress or PathValidationProgress(user=user)

    @staticmethod
    def apply(
        user: "User",
        item_count: int,
        check: Iterable[int],
        uncheck: Iterable[int],
    ) -> PathValidationProgress:
        with connection.cursor() as cursor:
            cursor.execute(
                _UPSERT_SQL,
                {
                    "user_id": user.id,
                    "item_count": item_count,
                    "check": indices_to_mask(check),
                    "uncheck": indices_to_mask(uncheck),
                },
            )
            row = cursor.fetchone()

        checked_items, stored_item_count, completed_at, updated_at = row
        return PathValidationProgress(
            user=user,
            checked_items=checked_items,
            item_count=stored_item_count,
            completed_at=completed_at,
            updated_at=updated_at,
        )
