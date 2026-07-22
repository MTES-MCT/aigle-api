from common.views.base import BaseViewSetMixin


from core.models.detection_data import DetectionData
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
        return queryset
