from typing import Generic, Optional, TypeVar
from django.db.models import Model, QuerySet

from core.models.user import User
from core.repository.base import BaseRepository


T_MODEL = TypeVar("T_MODEL", bound=Model)


class BasePermission(
    Generic[T_MODEL],
):
    repository: BaseRepository[T_MODEL]
    user: User

    def __init__(
        self, user: User, initial_queryset: Optional[QuerySet[T_MODEL]] = None
    ):
        raise NotImplementedError(
            f"Init method not implemented for {self.__class__.__name__}"
        )

    def list_(self, *args, **kwargs):
        raise NotImplementedError(
            f"list_ method not implemented for {self.__class__.__name__}"
        )
