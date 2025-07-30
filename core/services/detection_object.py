from typing import Optional, List, Dict, Any
from django.db import transaction
from django.contrib.gis.geos import Point

from core.models.detection_object import DetectionObject
from core.models.detection_data import DetectionValidationStatus
from core.models.tile_set import TileSetType
from core.permissions.tile_set import TileSetPermission
from core.services.prescription import PrescriptionService
from core.permissions.user import UserPermission


class DetectionObjectService:
    """Service for handling DetectionObject business logic."""

    @staticmethod
    def create_detection_object(
        object_type_id: str,
        user,
        address: Optional[str] = None,
        comment: Optional[str] = None,
        parcel_id: Optional[str] = None,
        location: Optional[Point] = None,
        user_group_ids: Optional[List[str]] = None,
        custom_zone_ids: Optional[List[str]] = None,
    ) -> DetectionObject:
        """Create a new DetectionObject with business logic validation."""
        # Validate user has access to specified user groups
        UserPermission(user=user).validate_user_group_access(
            user_group_ids=user_group_ids
        )

        with transaction.atomic():
            detection_object = DetectionObject.objects.create(
                address=address,
                comment=comment,
                object_type_id=object_type_id,
                parcel_id=parcel_id,
                location=location,
            )

            if user_group_ids:
                detection_object.user_groups.set(user_group_ids)

            if custom_zone_ids:
                detection_object.geo_custom_zones.set(custom_zone_ids)

            return detection_object

    @staticmethod
    def update_detection_object(
        detection_object: DetectionObject,
        user,
        address: Optional[str] = None,
        comment: Optional[str] = None,
        validation_status: Optional[DetectionValidationStatus] = None,
        user_group_ids: Optional[List[str]] = None,
        custom_zone_ids: Optional[List[str]] = None,
        compute_prescription_flag: bool = False,
    ) -> DetectionObject:
        """Update DetectionObject with business logic."""
        # Validate user has access to existing detection object
        UserPermission(user=user).validate_user_group_access_for_detection_object(
            detection_object=detection_object
        )

        # Validate user has access to new user groups if provided
        UserPermission(user=user).validate_user_group_access(
            user_group_ids=user_group_ids
        )

        with transaction.atomic():
            if address is not None:
                detection_object.address = address
            if comment is not None:
                detection_object.comment = comment

            detection_object.save()

            # Update relationships
            if user_group_ids is not None:
                detection_object.user_groups.set(user_group_ids)

            if custom_zone_ids is not None:
                detection_object.geo_custom_zones.set(custom_zone_ids)

            # Handle validation status change
            if validation_status is not None:
                DetectionObjectService._update_validation_status(
                    detection_object=detection_object,
                    validation_status=validation_status,
                )

            # Compute prescription if requested
            if compute_prescription_flag:
                PrescriptionService.compute_prescription(
                    detection_object=detection_object
                )

            return detection_object

    @staticmethod
    def _update_validation_status(
        detection_object: DetectionObject, validation_status: DetectionValidationStatus
    ):
        """Update validation status for all detections of this object."""
        detection_object.detections.update(validation_status=validation_status)

    @staticmethod
    def find_detections_by_coordinates(
        x: float, y: float, user, tile_set_types: Optional[List[TileSetType]] = None
    ) -> List[DetectionObject]:
        """Find detection objects at given coordinates with permission checks."""
        point = Point(x, y)

        # Apply user group permissions
        detection_objects = DetectionObject.objects.filter(
            location__intersects=point, user_groups__users=user
        )

        # Apply tile set type filters if specified
        if tile_set_types:
            detection_objects = detection_objects.filter(
                detections__tile__tile_set__type__in=tile_set_types
            ).distinct()

        return list(detection_objects)

    @staticmethod
    def get_detection_history_tile_sets(
        detection_object: DetectionObject, user
    ) -> List:
        """Get tile sets for detection history with user permissions."""
        detections = detection_object.detections.order_by("-tile_set__date").all()

        if not detections:
            return []

        # Get accessible tile sets using permissions
        tile_sets = TileSetPermission(user=user).list_(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            order_bys=["-date"],
            filter_tile_set_intersects_geometry=detections[0].geometry,
        )

        if not tile_sets:
            return []

        return sorted(tile_sets, key=lambda t: t.date)

    @staticmethod
    def get_detection_history_mapping(
        detection_object: DetectionObject,
    ) -> Dict[int, Any]:
        """Get mapping of tile set ID to detection for history."""
        detections = detection_object.detections.order_by("-tile_set__date").all()
        return {detection.tile_set.id: detection for detection in detections}

    @staticmethod
    def get_user_group_last_update(
        detection_object: DetectionObject,
    ) -> Optional[Dict[str, Any]]:
        """Get the user group of the last user who updated this detection object."""
        from core.services.detection import DetectionService

        most_recent_detection = DetectionService.get_most_recent_detection(
            detection_object=detection_object
        )

        if not most_recent_detection:
            return None

        detection_data = most_recent_detection.detection_data
        if not detection_data.user_last_update:
            return None

        user_user_group = detection_data.user_last_update.user_user_groups.order_by(
            "created_at"
        ).first()

        if not user_user_group:
            return None

        return {
            "id": user_user_group.user_group.id,
            "uuid": str(user_user_group.user_group.uuid),
            "name": user_user_group.user_group.name,
        }

    @staticmethod
    def get_filtered_detections_queryset(
        detection_object: DetectionObject,
        user,
        tile_set_previews: Optional[List[Dict]] = None,
    ):
        """Get filtered detections queryset for a detection object."""
        # Get tile set previews if not provided
        if tile_set_previews is None:
            tile_set_previews = TileSetPermission(user=user).get_previews(
                filter_tile_set_intersects_geometry=detection_object.detections.first().geometry,
            )

        # Filter detections by accessible tile sets
        return detection_object.detections.order_by("-tile_set__date").filter(
            tile_set__id__in=[preview["tile_set"].id for preview in tile_set_previews]
        )

    @staticmethod
    def get_tile_set_previews_data(detection_object: DetectionObject, user):
        """Get tile set previews data for a detection object."""
        if not detection_object.detections.exists():
            return []

        return TileSetPermission(user=user).get_previews(
            filter_tile_set_intersects_geometry=detection_object.detections.first().geometry,
        )

    @staticmethod
    def get_user_group_rights(detection_object: DetectionObject, user) -> List[str]:
        """Get user group rights for a detection object."""
        if not detection_object.detections.exists():
            return []

        from core.permissions.user import UserPermission

        detection_geometry = (
            detection_object.detections.order_by("-tile_set__date").first().geometry
        )
        point = detection_geometry.centroid
        user_permission = UserPermission(user)
        return user_permission.get_user_group_rights(points=[point])

    @staticmethod
    def get_custom_zones_reconciled(
        detection_object: DetectionObject,
    ) -> List[Dict[str, Any]]:
        """Get reconciled custom zones for a detection object."""
        from core.serializers.utils.custom_zones import (
            reconciliate_custom_zones_with_sub,
        )

        return reconciliate_custom_zones_with_sub(
            custom_zones=list(detection_object.geo_custom_zones.all()),
            sub_custom_zones=list(detection_object.geo_sub_custom_zones.all()),
        )

    @staticmethod
    def save_user_position(user, x: float, y: float) -> None:
        """Save user's last known position."""
        from core.services.user import UserService

        UserService.update_user_position(user=user, x=x, y=y)

    @staticmethod
    def get_detection_history_data(
        detection_object: DetectionObject, user
    ) -> List[Dict[str, Any]]:
        """Get detection history data for serialization."""
        detections = detection_object.detections.order_by("-tile_set__date").all()

        if not detections:
            return []

        tile_sets = TileSetPermission(user=user).list_(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            order_bys=["-date"],
            filter_tile_set_intersects_geometry=detections[0].geometry,
        )

        if not tile_sets:
            return []

        detection_history = []
        tile_set_id_detection_map = {
            detection.tile_set.id: detection for detection in detections
        }

        for tile_set in sorted(tile_sets, key=lambda t: t.date):
            detection = tile_set_id_detection_map.get(tile_set.id, None)

            detection_history.append({"tile_set": tile_set, "detection": detection})

        return detection_history

    @staticmethod
    def update_detection_object_comprehensive(
        detection_object: DetectionObject,
        user,
        address: Optional[str] = None,
        comment: Optional[str] = None,
        object_type_uuid: Optional[str] = None,
    ) -> DetectionObject:
        """Comprehensive update for detection object including business rules."""
        from core.services.detection import DetectionService
        from core.models.object_type import ObjectType
        from core.permissions.user import UserPermission

        # Validate permissions
        latest_detection = DetectionService.get_most_recent_detection(
            detection_object=detection_object
        )

        if latest_detection:
            UserPermission(user=user).can_edit(
                geometry=latest_detection.geometry, raise_exception=True
            )

        with transaction.atomic():
            # Update basic fields
            if address is not None:
                detection_object.address = address
            if comment is not None:
                detection_object.comment = comment

            # Handle object type change
            if (
                object_type_uuid
                and str(detection_object.object_type.uuid) != object_type_uuid
            ):
                object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()
                if not object_type:
                    raise ValueError(
                        f"Object type with uuid {object_type_uuid} not found"
                    )

                detection_object.object_type = object_type
                PrescriptionService.compute_prescription(
                    detection_object=detection_object
                )

                # Update validation status if needed
                if (
                    latest_detection
                    and latest_detection.detection_data.detection_validation_status
                    == DetectionValidationStatus.DETECTED_NOT_VERIFIED
                ):
                    latest_detection.detection_data.detection_validation_status = (
                        DetectionValidationStatus.SUSPECT
                    )
                    latest_detection.detection_data.save()

            detection_object.save()
            return detection_object
