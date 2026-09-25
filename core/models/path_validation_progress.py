from django.db import models
from django.db.models import F, Q
from django.db.models.lookups import Exact

from core.constants.help_center import PATH_VALIDATION_MAX_ITEM_COUNT
from core.models.user import User


class PathValidationProgress(models.Model):
    # Field order = column order: 8-byte columns first, so Postgres adds no alignment padding.
    user = models.OneToOneField(
        User,
        primary_key=True,
        related_name="path_validation_progress",
        on_delete=models.CASCADE,
    )
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True)
    # Bit i = item i of PATH_VALIDATION in aigle-frontend src/routes/HelpCenter/content/exercises.ts (append-only list).
    checked_items = models.PositiveIntegerField(default=0)
    item_count = models.SmallIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(
                    item_count__gte=1,
                    item_count__lte=PATH_VALIDATION_MAX_ITEM_COUNT,
                ),
                name="path_validation_progress_item_count_range",
            ),
            models.CheckConstraint(
                check=Q(Exact(F("checked_items").bitrightshift(F("item_count")), 0)),
                name="path_validation_progress_checked_items_in_range",
            ),
        ]
