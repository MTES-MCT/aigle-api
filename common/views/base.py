from typing import Generic

from typing import TypeVar

from rest_framework.viewsets import ModelViewSet

from common.models.deletable import DeletableModelMixin
from common.views.countable import CountableModelViewSetMixin
from common.views.deletable import DeletableModelViewSetMixin


T_DELETABLE_MODEL = TypeVar("T_DELETABLE_MODEL", bound=DeletableModelMixin)


class BaseViewSetMixin(
    Generic[T_DELETABLE_MODEL],
    DeletableModelViewSetMixin[T_DELETABLE_MODEL],
    CountableModelViewSetMixin,
    ModelViewSet,
):
    lookup_field = "uuid"

    http_method_names = ["get", "post", "put", "patch", "head", "options", "trace"]

    def get_serializer_context(self):
        return {"request": self.request}
