from datetime import datetime
from typing import Generic

from typing import TypeVar

from common.models.deletable import DeletableModelMixin


T_DELETABLE_MODEL = TypeVar("T_DELETABLE_MODEL", bound=DeletableModelMixin)


class DeletableModelViewSetMixin(Generic[T_DELETABLE_MODEL]):
    def perform_destroy(self, instance: T_DELETABLE_MODEL):
        instance.deleted = True
        instance.deleted_at = datetime.now()
        instance.save()
