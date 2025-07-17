from typing import Optional
from core.models.parcel import Parcel
from core.models.user import User
from core.permissions.base import BasePermission

from django.db.models import QuerySet

from core.repository.parcel import ParcelRepository


class ParcelPermission(
    BasePermission[Parcel],
):
    def __init__(self, user: User, initial_queryset: Optional[QuerySet[Parcel]] = None):
        self.repository = ParcelRepository(initial_queryset=initial_queryset)
        self.user = user
