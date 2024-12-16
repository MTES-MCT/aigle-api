from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from django.contrib.postgres.fields import ArrayField
from django.contrib.auth import get_user_model

from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_zone import GeoZone
from core.models.object_type_category import ObjectTypeCategory

UserModel = get_user_model()


class UserGroupType(models.TextChoices):
    DDTM = "DDTM", "DDTM"
    COLLECTIVITY = "COLLECTIVITY", "COLLECTIVITY"


class UserGroup(TimestampedModelMixin, UuidModelMixin, DeletableModelMixin):
    name = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True)
    geo_zones = models.ManyToManyField(GeoZone, related_name="user_groups")
    geo_custom_zones = models.ManyToManyField(
        GeoCustomZone, related_name="user_groups_custom_geo_zones"
    )
    object_type_categories = models.ManyToManyField(
        ObjectTypeCategory, related_name="user_groups"
    )
    user_group_type = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=UserGroupType.choices,
    )

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + []


class UserGroupRight(models.TextChoices):
    WRITE = "WRITE", "WRITE"
    ANNOTATE = "ANNOTATE", "ANNOTATE"
    READ = "READ", "READ"


class UserUserGroup(TimestampedModelMixin):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "user_group"], name="user_user_group_unique"
            ),
        ]
        indexes = [
            models.Index(
                fields=["user_id", "user_group_id"],
                name="idx_user_group_id",
            ),
        ]

    user_group_rights = ArrayField(
        models.CharField(
            max_length=DEFAULT_MAX_LENGTH,
            choices=UserGroupRight.choices,
        )
    )
    user = models.ForeignKey(
        UserModel, related_name="user_user_groups", on_delete=models.CASCADE
    )
    user_group = models.ForeignKey(
        UserGroup, related_name="user_user_groups", on_delete=models.CASCADE
    )
