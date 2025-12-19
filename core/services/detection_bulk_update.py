from typing import List, Dict, Any, Optional
from django.contrib.gis.geos import MultiPolygon

from core.models.detection import Detection
from core.models.object_type import ObjectType
from core.permissions.user import UserPermission
from django.core.exceptions import BadRequest


class DetectionBulkUpdateService:
    """Service for handling bulk detection updates."""

    def __init__(self, user):
        self.user = user

    def update_multiple_detections(
        self, detections: List[Detection], update_data: Dict[str, Any]
    ) -> List[Detection]:
        """Update multiple detections with business logic validation."""
        # Check permissions for all geometries
        self._validate_edit_permissions(detections)

        # Validate object type if provided
        object_type = self._validate_and_get_object_type(
            update_data.get("object_type_uuid")
        )

        # Determine fields to update
        detection_data_fields_to_update = self._get_fields_to_update(update_data)

        # Process updates
        detection_datas_to_update = []
        detection_objects_to_update = []

        for detection in detections:
            # Update detection data fields
            if detection_data_fields_to_update:
                self._update_detection_data_fields(
                    detection, detection_data_fields_to_update, update_data
                )

                detection.detection_data.user_last_update = self.user
                detection_datas_to_update.append(detection.detection_data)

            # Update object type if provided
            if object_type:
                detection.detection_object.object_type = object_type
                detection_objects_to_update.append(detection.detection_object)

        # Bulk update database
        if detection_data_fields_to_update or detection_objects_to_update:
            self._perform_bulk_updates(
                detection_datas_to_update,
                detection_objects_to_update,
                detection_data_fields_to_update + ["user_last_update"],
            )

        return detections

    def _validate_edit_permissions(self, detections: List[Detection]) -> None:
        """Validate user has permission to edit all detections."""
        geometries = [detection.geometry for detection in detections]
        UserPermission(user=self.user).can_edit(
            geometry=MultiPolygon(geometries), raise_exception=True
        )

    def _validate_and_get_object_type(
        self, object_type_uuid: Optional[str]
    ) -> Optional[ObjectType]:
        """Validate and retrieve object type if UUID provided."""
        if not object_type_uuid:
            return None

        object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()
        if not object_type:
            raise BadRequest(
                f"Object type with following uuid not found: {object_type_uuid}"
            )
        return object_type

    def _get_fields_to_update(self, update_data: Dict[str, Any]) -> List[str]:
        """Determine which detection data fields need updating."""
        fields = []
        if update_data.get("detection_control_status"):
            fields.append("detection_control_status")
        if update_data.get("detection_validation_status"):
            fields.append("detection_validation_status")
        return fields

    def _update_detection_data_fields(
        self,
        detection: Detection,
        fields_to_update: List[str],
        update_data: Dict[str, Any],
    ) -> None:
        """Update detection data fields with new values."""
        for field in fields_to_update:
            if field == "detection_control_status":
                detection.detection_data.set_detection_control_status(
                    update_data[field]
                )
                continue

            setattr(
                detection.detection_data,
                field,
                update_data[field],
            )

    def _perform_bulk_updates(
        self,
        detection_datas_to_update: List,
        detection_objects_to_update: List,
        detection_data_fields_to_update: List[str],
    ) -> None:
        """Perform bulk database updates with history tracking."""
        from core.models.detection_data import DetectionData
        from core.models.detection_object import DetectionObject
        from simple_history.utils import bulk_update_with_history

        if detection_datas_to_update:
            bulk_update_with_history(
                detection_datas_to_update,
                DetectionData,
                detection_data_fields_to_update,
            )

        if detection_objects_to_update:
            bulk_update_with_history(
                detection_objects_to_update, DetectionObject, ["object_type"]
            )
