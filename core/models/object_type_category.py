from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin

from core.models.object_type import ObjectType


class ObjectTypeCategory(TimestampedModelMixin, UuidModelMixin, DeletableModelMixin):
    name = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True)

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + []


class ObjectTypeCategoryObjectTypeStatus(models.TextChoices):
    VISIBLE = "VISIBLE", "VISIBLE"
    OTHER_CATEGORY = "OTHER_CATEGORY", "OTHER_CATEGORY"
    HIDDEN = "HIDDEN", "HIDDEN"


class ObjectTypeCategoryObjectType(TimestampedModelMixin):
    object_type_category = models.ForeignKey(
        ObjectTypeCategory,
        related_name="object_type_category_object_types",
        on_delete=models.CASCADE,
    )
    object_type = models.ForeignKey(
        ObjectType,
        related_name="object_type_category_object_types",
        on_delete=models.CASCADE,
    )
    object_type_category_object_type_status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=ObjectTypeCategoryObjectTypeStatus.choices,
    )
