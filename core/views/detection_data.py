from common.views.base import BaseViewSetMixin


from core.models.detection_data import DetectionData
from core.permissions.user import UserPermission
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

    def perform_destroy(self, instance):
        # Deletion must respect the same geo-zone write scope as edition
        # (DetectionDataInputSerializer.update enforces this). Without it, any
        # authenticated user could soft-delete detection data outside their zones.
        UserPermission.from_request(self.request).can_edit(
            geometry=instance.detection.geometry, raise_exception=True
        )
        super().perform_destroy(instance)
