from datetime import datetime
from django.db import models

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin

from django.utils.translation import gettext_lazy as _

from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from core.managers.user import UserManager
from django.contrib.gis.db import models as models_gis
from simple_history.models import HistoricalRecords
from common.models.historied import HistoriedModelMixin


class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "SUPER_ADMIN"
    ADMIN = "ADMIN", "ADMIN"
    REGULAR = "REGULAR", "REGULAR"


class User(
    AbstractBaseUser,
    PermissionsMixin,
    TimestampedModelMixin,
    UuidModelMixin,
    DeletableModelMixin,
):
    email = models.EmailField(
        unique=True,
        max_length=255,
        blank=False,
    )

    # AbstractBaseUser definitions

    first_name = None
    last_name = None
    is_staff = None
    is_active = models.BooleanField(_("active"), default=True)
    date_joined = models.DateTimeField(_("date joined"), default=datetime.now)

    # Additional fields

    user_role = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=UserRole.choices,
        default=UserRole.REGULAR,
    )
    last_position = models_gis.PointField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["user_role"]

    history = HistoricalRecords(bases=[HistoriedModelMixin])
