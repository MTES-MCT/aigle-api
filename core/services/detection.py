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
from core.models.geo_commune import GeoCommune
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_sub_custom_zone import GeoSubCustomZone
from core.models.object_type import ObjectType
from core.models.parcel import Parcel
from core.models.tile import Tile, TILE_DEFAULT_ZOOM
from core.models.tile_set import TileSet, TileSetStatus, TileSetType
from core.services.prescription import PrescriptionService
from core.permissions.detection import DetectionPermission


class DetectionService:
    @staticmethod
    def get_linked_detections(
        detection_geometry: GEOSGeometry,
        object_type_id: int,
        exclude_tile_set_ids: Iterable[int],
    ) -> List[Detection]:
        linked_detections_queryset = Detection.objects

        linked_detections_queryset = linked_detections_queryset.filter(
            ~Q(tile_set__id__in=exclude_tile_set_ids)
        )
        linked_detections_queryset = linked_detections_queryset.filter(
            geometry__intersects=detection_geometry,
            detection_object__object_type__id=object_type_id,
        )
        linked_detections_queryset = linked_detections_queryset.annotate(
            intersection_area=Area(Intersection("geometry", Value(detection_geometry)))
        )
        # most recent tile set wins; largest overlap breaks ties within the same date
        linked_detections_queryset = linked_detections_queryset.order_by(
            "-tile_set__date", "-intersection_area"
        )
        linked_detections_queryset = linked_detections_queryset.select_related(
            "detection_object", "detection_data"
        )

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

    # Atomic because the rights check below can only run once the DetectionObject is
    # resolved — which, for a new one, means it is already saved (with its custom-zone
    # M2M rows). Without this, a denied creation returns 403 and still leaves it behind.
    @staticmethod
    @transaction.atomic()
    def create_detection(
        geometry: GEOSGeometry,
        user,
        tile_set_uuid: str,
        detection_object_uuid: Optional[str] = None,
        detection_object_data: Optional[Dict[str, Any]] = None,
        detection_data_data: Optional[Dict[str, Any]] = None,
        scoped_user_group=None,
    ) -> Detection:
        tile_set = TileSet.objects.filter(uuid=tile_set_uuid).first()
        if not tile_set:
            raise ValueError(f"Tile set with uuid {tile_set_uuid} not found")

        # A detection must fall inside the tile set's geographic coverage. Without this
        # guard, a caller reusing a detection_object across tile sets (the "force visible
        # on every background" flow) can attach a geometry to a tile set thousands of km
        # away — the source of cross-region junk detections. Only enforced when the tile
        # set declares geo_zones with a geometry (some background tile sets legitimately
        # have none, and GeoZone.geometry is nullable — a NULL-geometry zone must not
        # turn the guard into a blanket rejection).
        tile_set_zones = tile_set.geo_zones.filter(geometry__isnull=False)
        if (
            tile_set_zones.exists()
            and not tile_set_zones.filter(geometry__intersects=geometry).exists()
        ):
            raise ValueError("Detection geometry is outside the tile set coverage")

        centroid = Centroid(geometry)
        tile = Tile.objects.filter(
            geometry__contains=centroid, z=TILE_DEFAULT_ZOOM
        ).first()

        if not tile:
            raise ValueError("Tile not found for specified geometry")

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

        # Creation is scoped by the object's commune like every other write — for a new
        # object the one resolved from the centroid above, otherwise the one of the
        # object the caller named or the drawn geometry got linked to ("force visible on
        # another background"), which may sit outside the drawer's perimeter.
        DetectionPermission(
            user=user, scoped_user_group=scoped_user_group
        ).validate_detection_object_edit_permission(detection_object=detection_object)

        detection_data = DetectionService._create_detection_data(
            detection_data_data=detection_data_data,
            detection_object=detection_object,
            user=user,
        )

        detection = Detection(
            geometry=geometry,
            detection_object=detection_object,
            detection_data=detection_data,
            tile_set=tile_set,
            tile=tile,
        )
        detection.save()

        PrescriptionService.compute_prescription(detection_object=detection_object)

        return detection

    @staticmethod
    def _create_or_find_detection_object(
        geometry: GEOSGeometry,
        centroid,
        detection_object_data: Dict[str, Any],
        tile_set: TileSet,
    ) -> DetectionObject:
        object_type_uuid = detection_object_data.pop("object_type_uuid")
        object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()

        if not object_type:
            raise ValueError(f"Object type with uuid {object_type_uuid} not found")

        linked_detections = DetectionService.get_linked_detections(
            detection_geometry=geometry,
            object_type_id=object_type.id,
            exclude_tile_set_ids=[tile_set.id],
        )

        if linked_detections:
            return linked_detections[0].detection_object

        detection_object = DetectionObject(**detection_object_data)
        detection_object.object_type = object_type

        parcel = (
            Parcel.objects.filter(geometry__contains=centroid)
            .select_related("commune")
            .defer("geometry", "commune__geometry")
            .first()
        )

        commune = (
            GeoCommune.objects.filter(geometry__contains=centroid).only("id").first()
        )

        if commune is None:
            raise ValueError("Commune not found for input geometry")

        detection_object.parcel = parcel
        detection_object.commune_id = commune.id
        detection_object.save()

        # A detection belongs to every custom zone whose geometry fully covers it
        # (deliberate rule: the zone must contain the whole detection, not merely clip
        # it). Matched purely spatially through the GiST index on GeoZone.geometry —
        # no filter on the zone's geo_zones M2M, which is only a coarse collectivity
        # label (a ZAE zone lists just its department, a hand-drawn zone may list
        # nothing); gating on it silently dropped zones that actually cover the
        # detection. Same scope as the bulk recompute
        # GeoCustomZoneService.associate_detections_to_custom_zones.
        geo_custom_zones = list(GeoCustomZone.objects.filter(geometry__covers=geometry))
        detection_object.geo_custom_zones.add(*geo_custom_zones)

        geo_sub_custom_zones = GeoSubCustomZone.objects.filter(
            custom_zone__in=geo_custom_zones,
            geometry__covers=geometry,
        )
        detection_object.geo_sub_custom_zones.add(*geo_sub_custom_zones)

        return detection_object

    @staticmethod
    def _create_detection_data(
        detection_data_data: Optional[Dict[str, Any]],
        detection_object: DetectionObject,
        user,
    ) -> DetectionData:
        if detection_data_data:
            detection_data = DetectionData(**detection_data_data)
        else:
            detection_data = DetectionData(
                detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
                detection_validation_status=DetectionValidationStatus.SUSPECT,
            )

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
        detection: Detection,
        object_type_uuid: str,
        user,
        scoped_user_group=None,
    ) -> Detection:
        DetectionPermission(
            user=user, scoped_user_group=scoped_user_group
        ).validate_detections_edit_permission(detections=[detection])

        object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()
        if not object_type:
            raise ValueError(f"Object type with uuid {object_type_uuid} not found")

        with transaction.atomic():
            detection.detection_object.object_type = object_type
            detection.detection_object.save()

            PrescriptionService.compute_prescription(
                detection_object=detection.detection_object
            )

            detection.save()
            return detection
