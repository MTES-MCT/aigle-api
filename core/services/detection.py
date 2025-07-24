from typing import List, Optional, Iterable, Dict, Any
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.db.models.functions import Intersection, Area, Centroid
from django.db.models import Value, Q
from django.db import transaction

from core.constants.detection import PERCENTAGE_SAME_DETECTION_THRESHOLD
from core.models.detection import Detection
from core.models.detection_object import DetectionObject
from core.models.detection_data import (
    DetectionData,
    DetectionControlStatus,
    DetectionValidationStatus,
    DetectionPrescriptionStatus,
)
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_sub_custom_zone import GeoSubCustomZone
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.object_type import ObjectType
from core.models.parcel import Parcel
from core.models.tile import Tile, TILE_DEFAULT_ZOOM
from core.models.tile_set import TileSet, TileSetStatus, TileSetType
from core.services.prescription import PrescriptionService
from core.permissions.user import UserPermission


class DetectionService:
    """Service for handling Detection business logic."""

    @staticmethod
    def get_linked_detections(
        detection_geometry: GEOSGeometry,
        object_type_id: int,
        exclude_tile_set_ids: Iterable[int],
    ) -> List[Detection]:
        """Find detections linked to given geometry and object type."""
        linked_detections_queryset = Detection.objects

        linked_detections_queryset = linked_detections_queryset.filter(
            ~Q(tile_set__id__in=exclude_tile_set_ids)
        )
        linked_detections_queryset = linked_detections_queryset.order_by(
            "-tile_set__date"
        )
        linked_detections_queryset = linked_detections_queryset.filter(
            geometry__intersects=detection_geometry,
            detection_object__object_type__id=object_type_id,
        )
        linked_detections_queryset = linked_detections_queryset.annotate(
            intersection_area=Area(Intersection("geometry", Value(detection_geometry)))
        )
        linked_detections_queryset = linked_detections_queryset.order_by(
            "-intersection_area"
        )
        linked_detections_queryset = linked_detections_queryset.select_related(
            "detection_object", "detection_object__object_type", "tile_set"
        )

        # Filter out detections that have too small intersection area
        return list(
            [
                detection
                for detection in linked_detections_queryset.all()
                if detection.intersection_area.sq_m
                >= detection_geometry.area * PERCENTAGE_SAME_DETECTION_THRESHOLD
                or detection.intersection_area.sq_m
                >= detection.geometry.area * PERCENTAGE_SAME_DETECTION_THRESHOLD
            ]
        )

    @staticmethod
    def get_most_recent_detection(
        detection_object: DetectionObject,
    ) -> Optional[Detection]:
        """Get the most recent detection for a detection object."""
        return (
            detection_object.detections.exclude(
                tile_set__tile_set_status=TileSetStatus.DEACTIVATED
            )
            .filter(
                tile_set__tile_set_type__in=[
                    TileSetType.BACKGROUND,
                    TileSetType.PARTIAL,
                ]
            )
            .select_related("detection_data")
            .order_by("-tile_set__date")
            .first()
        )

    @staticmethod
    def create_detection(
        geometry: GEOSGeometry,
        user,
        tile_set_uuid: str,
        detection_object_uuid: Optional[str] = None,
        detection_object_data: Optional[Dict[str, Any]] = None,
        detection_data_data: Optional[Dict[str, Any]] = None,
    ) -> Detection:
        """Create a new detection with full business logic."""
        # Validate permissions
        UserPermission(user=user).validate_geometry_edit_permission(geometry=geometry)

        with transaction.atomic():
            # Get tile set
            tile_set = TileSet.objects.filter(uuid=tile_set_uuid).first()
            if not tile_set:
                raise ValueError(f"Tile set with uuid {tile_set_uuid} not found")

            # Find tile
            centroid = Centroid(geometry)
            tile = Tile.objects.filter(
                geometry__contains=centroid, z=TILE_DEFAULT_ZOOM
            ).first()

            if not tile:
                raise ValueError("Tile not found for specified geometry")

            # Handle detection object
            detection_object = None

            if detection_object_uuid:
                detection_object = DetectionObject.objects.filter(
                    uuid=detection_object_uuid
                ).first()
                if not detection_object:
                    raise ValueError(
                        f"Detection object with uuid {detection_object_uuid} not found"
                    )
            else:
                if not detection_object_data:
                    raise ValueError("Detection object data or UUID must be specified")

                detection_object = DetectionService._create_or_find_detection_object(
                    geometry=geometry,
                    centroid=centroid,
                    detection_object_data=detection_object_data,
                    tile_set=tile_set,
                )

            # Create detection data
            detection_data = DetectionService._create_detection_data(
                detection_data_data=detection_data_data,
                detection_object=detection_object,
                user=user,
            )

            # Create detection
            detection = Detection(
                geometry=geometry,
                detection_object=detection_object,
                detection_data=detection_data,
                tile_set=tile_set,
                tile=tile,
            )
            detection.save()

            # Update prescription
            PrescriptionService.compute_prescription(detection_object=detection_object)

            return detection

    @staticmethod
    def _create_or_find_detection_object(
        geometry: GEOSGeometry,
        centroid,
        detection_object_data: Dict[str, Any],
        tile_set: TileSet,
    ) -> DetectionObject:
        """Create or find existing detection object."""
        object_type_uuid = detection_object_data.pop("object_type_uuid")
        object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()

        if not object_type:
            raise ValueError(f"Object type with uuid {object_type_uuid} not found")

        # Search for existing detection object
        linked_detections = DetectionService.get_linked_detections(
            detection_geometry=geometry,
            object_type_id=object_type.id,
            exclude_tile_set_ids=[tile_set.id],
        )

        if linked_detections:
            return linked_detections[0].detection_object

        # Create new detection object
        detection_object = DetectionObject(**detection_object_data)
        detection_object.object_type = object_type

        # Find parcel
        parcel = (
            Parcel.objects.filter(geometry__contains=centroid)
            .select_related("commune")
            .defer("geometry", "commune__geometry")
            .first()
        )

        # Find commune
        commune_id = None
        if parcel and parcel.commune:
            commune_id = parcel.commune.id
        else:
            commune_ids = (
                GeoZone.objects.filter(
                    geo_zone_type=GeoZoneType.COMMUNE,
                    geometry__contains=centroid,
                )
                .values_list("id")
                .first()
            )
            if commune_ids:
                commune_id = commune_ids[0]

        detection_object.parcel = parcel
        detection_object.commune_id = commune_id
        detection_object.save()

        # Update geo_custom_zones
        geo_custom_zones = GeoCustomZone.objects.filter(
            geometry__contains=geometry
        ).all()
        detection_object.geo_custom_zones.add(*geo_custom_zones)

        geo_sub_custom_zones = GeoSubCustomZone.objects.filter(
            geometry__contains=geometry
        ).all()
        detection_object.geo_sub_custom_zones.add(*geo_sub_custom_zones)

        return detection_object

    @staticmethod
    def _create_detection_data(
        detection_data_data: Optional[Dict[str, Any]],
        detection_object: DetectionObject,
        user,
    ) -> DetectionData:
        """Create detection data with business rules."""
        if detection_data_data:
            detection_data = DetectionData(**detection_data_data)
        else:
            detection_data = DetectionData(
                detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
                detection_validation_status=DetectionValidationStatus.SUSPECT,
            )

        # Handle prescription status based on object type
        if (
            detection_data.detection_prescription_status is None
            and detection_object.object_type.prescription_duration_years
        ):
            detection_data.detection_prescription_status = (
                DetectionPrescriptionStatus.NOT_PRESCRIBED
            )

        if (
            detection_data.detection_prescription_status is not None
            and not detection_object.object_type.prescription_duration_years
        ):
            detection_data.detection_prescription_status = None

        detection_data.user_last_update = user
        detection_data.save()

        return detection_data

    @staticmethod
    def update_detection_object_type(
        detection: Detection, object_type_uuid: str, user
    ) -> Detection:
        """Update detection object type with business rules."""
        # Validate permissions
        UserPermission(user=user).validate_geometry_edit_permission(
            geometry=detection.geometry
        )

        object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()
        if not object_type:
            raise ValueError(f"Object type with uuid {object_type_uuid} not found")

        with transaction.atomic():
            detection.detection_object.object_type = object_type
            detection.detection_object.save()

            # Update prescription
            PrescriptionService.compute_prescription(
                detection_object=detection.detection_object
            )

            detection.save()
            return detection
