from common.views.base import BaseViewSetMixin

from operator import or_
from django.db.models import Q
from functools import reduce
from django_filters import FilterSet
from django_filters import NumberFilter, ChoiceFilter
from core.contants.geo import SRID
from core.models.detection import Detection, DetectionSource
from django.core.exceptions import BadRequest

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionValidationStatus,
)
from django.http import HttpResponse
from rest_framework.status import HTTP_200_OK, HTTP_202_ACCEPTED
from core.models.detection_object import DetectionObject
from core.models.object_type import ObjectType
from core.models.tile_set import TileSetStatus, TileSetType
from core.models.user import UserRole
from core.models.user_group import UserGroupRight
from core.permissions.tile_set import TileSetPermission
from core.permissions.user import UserPermission
from core.repository.detection import (
    DetectionRepository,
    RepoFilterCustomZone,
    RepoFilterInterfaceDrawn,
)
from core.serializers.detection import (
    DetectionDetailSerializer,
    DetectionInputSerializer,
    DetectionMinimalSerializer,
    DetectionMultipleInputSerializer,
    DetectionSerializer,
    DetectionUpdateSerializer,
)
from core.utils.data_permissions import (
    get_user_group_rights,
    get_user_object_types_with_status,
)
from simple_history.utils import bulk_update_with_history
from core.utils.filters import ChoiceInFilter, UuidInFilter
from django.contrib.gis.geos import Polygon
from rest_framework.decorators import action

from core.views.detection.utils import (
    BOOLEAN_CHOICES,
    INTERFACE_DRAWN_CHOICES,
    filter_custom_zones_uuids,
    filter_prescripted,
    filter_score,
)


class DetectionGeoFilter(FilterSet):
    objectTypesUuids = UuidInFilter(method="pass_")
    customZonesUuids = UuidInFilter(method="pass_")
    tileSetsUuids = UuidInFilter(method="pass_")
    detectionValidationStatuses = ChoiceInFilter(
        field_name="detection_data__detection_validation_status",
        choices=DetectionValidationStatus.choices,
    )
    detectionControlStatuses = ChoiceInFilter(
        field_name="detection_data__detection_control_status",
        choices=DetectionControlStatus.choices,
    )
    detectionPrescriptionStatuses = ChoiceInFilter(
        field_name="detection_data__detection_prescription_status",
        choices=DetectionControlStatus.choices,
    )

    communesUuids = UuidInFilter(method="pass_")
    departmentsUuids = UuidInFilter(method="pass_")
    regionsUuids = UuidInFilter(method="pass_")

    neLat = NumberFilter(method="pass_")
    neLng = NumberFilter(method="pass_")

    swLat = NumberFilter(method="pass_")
    swLng = NumberFilter(method="pass_")

    score = NumberFilter(method="filter_score")
    prescripted = ChoiceFilter(choices=BOOLEAN_CHOICES, method="filter_prescripted")
    interfaceDrawn = ChoiceFilter(
        choices=[(choice.value, choice.name) for choice in RepoFilterInterfaceDrawn],
        method="pass_",
    )

    def pass_(self, queryset, name, value):
        return queryset

    class Meta:
        model = Detection
        fields = ["neLat", "neLng", "swLat", "swLng", "tileSetsUuids"]
        geo_field = "geometry"

    def filter_score(self, queryset, name, value):
        return filter_score(queryset, name, value)

    def filter_prescripted(self, queryset, name, value):
        return filter_prescripted(queryset, name, value)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)

        # filter object types

        object_types_uuids = (
            self.data.get("objectTypesUuids").split(",")
            if self.data.get("objectTypesUuids")
            else []
        )

        if not object_types_uuids:
            object_types_with_status = get_user_object_types_with_status(
                self.request.user
            )
            object_types_uuids = [
                object_type_with_status[0].uuid
                for object_type_with_status in object_types_with_status
            ]

        queryset = queryset.filter(
            detection_object__object_type__uuid__in=object_types_uuids
        )

        # filter tile sets

        tile_sets_uuids = (
            self.data.get("tileSetsUuids").split(",")
            if self.data.get("tileSetsUuids")
            else []
        )

        # get geometry total

        # geomtery requested

        ne_lat = self.data.get("neLat")
        ne_lng = self.data.get("neLng")
        sw_lat = self.data.get("swLat")
        sw_lng = self.data.get("swLng")

        if not ne_lat or not ne_lng or not sw_lat or not sw_lng:
            polygon_requested = None
        else:
            polygon_requested = Polygon.from_bbox((sw_lng, sw_lat, ne_lng, ne_lat))
            polygon_requested.srid = SRID

        filter_tile_set_status__in = None

        if self.request.user.user_role == UserRole.SUPER_ADMIN:
            filter_tile_set_status__in = [
                TileSetStatus.VISIBLE,
                TileSetStatus.HIDDEN,
                TileSetStatus.DEACTIVATED,
            ]

        geometry_accessible = UserPermission(
            user=self.request.user
        ).get_accessible_geometry(intersects_geometry=polygon_requested)

        if not geometry_accessible:
            return []

        queryset = queryset.filter(geometry__intersects=geometry_accessible)

        tile_sets = TileSetPermission(
            user=self.request.user,
        ).list_(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            filter_tile_set_status_in=filter_tile_set_status__in,
            filter_tile_set_intersects_geometry=geometry_accessible,
            filter_tile_set_uuid_in=tile_sets_uuids,
            with_intersection=True,
        )

        wheres = []

        for i in range(len(tile_sets)):
            tile_set = tile_sets[i]
            previous_tile_sets = tile_sets[:i]
            where = Q(tile_set__uuid=tile_set.uuid)

            if tile_set.intersection:
                where &= Q(geometry__intersects=tile_set.intersection)
            elif geometry_accessible:
                where &= Q(geometry__intersects=geometry_accessible)

            for previous_tile_set in previous_tile_sets:
                # custom logic here: we want to display the detections on the last tileset
                # if the last tileset for a zone is partial, we also want to display detections for the last BACKGROUND tileset
                if (
                    tile_set.tile_set_type == TileSetType.BACKGROUND
                    and previous_tile_set.tile_set_type == TileSetType.PARTIAL
                ):
                    continue

                where &= ~Q(geometry__intersects=previous_tile_set.intersection)

            wheres.append(where)

            # if no geometry, we can stop the loop
            if not tile_set.intersection:
                break

        if len(wheres) == 1:
            queryset = queryset.filter(wheres[0])

        if len(wheres) > 1:
            queryset = queryset.filter(reduce(or_, wheres))

        filter_custom_zone = RepoFilterCustomZone(
            custom_zone_uuids=(
                self.data.get("customZonesUuids").split(",")
                if self.data.get("customZonesUuids")
                else []
            ),
            interface_drawn=RepoFilterInterfaceDrawn[
                self.data.get(
                    "interfaceDrawn",
                    RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES.value,
                )
            ],
        )
        detections = DetectionRepository(initial_queryset=queryset).list_(
            filter_custom_zone=filter_custom_zone
        )

        return detections


class DetectionGeoViewSet(BaseViewSetMixin[Detection]):
    filterset_class = DetectionGeoFilter

    @action(methods=["post"], detail=False, url_path="multiple")
    def edit_multiple(self, request):
        serializer = DetectionMultipleInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        detections_queryset = self.get_queryset()
        detections_queryset = detections_queryset.filter(
            uuid__in=serializer.validated_data["uuids"]
        )
        detections = detections_queryset.all()

        points = [detection.geometry.centroid for detection in detections]

        get_user_group_rights(
            user=request.user, points=points, raise_if_has_no_right=UserGroupRight.WRITE
        )

        detection_data_fields_to_update = []

        if serializer.validated_data.get("detection_control_status"):
            detection_data_fields_to_update.append("detection_control_status")
        if serializer.validated_data.get("detection_validation_status"):
            detection_data_fields_to_update.append("detection_validation_status")

        object_type = None
        if serializer.validated_data.get("object_type_uuid"):
            object_type_uuid = serializer.validated_data.get("object_type_uuid")
            object_type = ObjectType.objects.filter(uuid=object_type_uuid).first()

            if not object_type:
                raise BadRequest(
                    f"Object type with following uuid not found: {
                        object_type_uuid}"
                )

        detection_datas_to_update = []
        detection_objects_to_update = []

        for detection in detections:
            if detection_data_fields_to_update:
                for field in detection_data_fields_to_update:
                    setattr(
                        detection.detection_data,
                        field,
                        serializer.validated_data[field],
                    )

                detection_datas_to_update.append(detection.detection_data)

            if object_type:
                detection.detection_object.object_type = object_type
                detection_objects_to_update.append(detection.detection_object)

        if detection_data_fields_to_update:
            bulk_update_with_history(
                detection_datas_to_update,
                DetectionData,
                detection_data_fields_to_update,
            )

        if object_type:
            bulk_update_with_history(
                detection_objects_to_update, DetectionObject, ["object_type"]
            )

        return HttpResponse(status=HTTP_200_OK)

    def get_serializer_class(self):
        if self.action in ["create"]:
            return DetectionInputSerializer

        if self.action in ["partial_update", "update"]:
            return DetectionUpdateSerializer

        detail = bool(self.request.query_params.get("detail"))
        geo_feature = bool(self.request.query_params.get("geoFeature"))

        if self.action in ["list"] and geo_feature:
            return DetectionMinimalSerializer

        if detail:
            return DetectionDetailSerializer

        return DetectionSerializer

    def get_queryset(self):
        queryset = Detection.objects.order_by("tile_set__date", "id")
        queryset = queryset.prefetch_related(
            "detection_object", "detection_object__object_type", "tile", "tile_set"
        ).select_related("detection_data")
        return queryset

    @action(methods=["patch"], detail=True, url_path="force-visible")
    def force_visible(self, request, uuid, *args, **kwargs):
        queryset = self.get_queryset()
        queryset = queryset.filter(uuid=uuid)
        detection = queryset.first()

        detection.detection_source = DetectionSource.INTERFACE_FORCED_VISIBLE
        detection.save()

        return HttpResponse(status=HTTP_202_ACCEPTED)
