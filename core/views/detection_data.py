from common.views.base import BaseViewSetMixin


from rest_framework.permissions import SAFE_METHODS

from core.models.detection_data import DetectionData
from core.permissions.detection import DetectionPermission
from core.serializers.detection_data import (
    DetectionDataInputSerializer,
    DetectionDataSerializer,
)


class DetectionDataViewSet(BaseViewSetMixin[DetectionData]):
    def get_serializer_class(self):
        if self.action in ["partial_update", "update"]:
            return DetectionDataInputSerializer

        return DetectionDataSerializer

    def get_queryset(self):
        queryset = DetectionData.objects.order_by("-user_last_update")

        # Le queryset n'était pas borné : statuts de contrôle, dates de PV et références
        # d'autorisation de n'importe quelle détection étaient lisibles par tout compte
        # authentifié. Les écritures, elles, passaient déjà par le serializer, qui rend
        # un 403 explicite — d'où le filtrage limité aux méthodes sûres.
        if self.request.method in SAFE_METHODS:
            readable_q = DetectionPermission.from_request(
                self.request
            ).get_readable_objects_q("detection__detection_object__")
            if readable_q is not None:
                queryset = queryset.filter(readable_q)

        return queryset
