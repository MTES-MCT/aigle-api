from enum import Enum
from typing import List, Optional
from django.db.models import QuerySet

from core.models.detection import Detection
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.repository.base import (
    BaseRepository,
    DateFilter,
    NumberFilter,
    TimestampedBaseRepositoryMixin,
    UuidBaseRepositoryMixin,
)
from django.db.models import F, Q
from django.contrib.gis.geos import Polygon


class FilterInterfaceDrawn(Enum):
    ALL = "ALL"
    INSIDE_SELECTED_ZONES = "INSIDE_SELECTED_ZONES"
    NONE = "NONE"


class DetectionRepository(
    BaseRepository[Detection],
    TimestampedBaseRepositoryMixin[Detection],
    UuidBaseRepositoryMixin[Detection],
):
    def _filter(
        self,
        filter_created_at: Optional[DateFilter] = None,
        filter_updated_at: Optional[DateFilter] = None,
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
        filter_collectivity_uuid_in: Optional[List[str]] = None,
        filter_score: Optional[NumberFilter] = None,
        filter_object_type_uuid_in: Optional[List[str]] = None,
        filter_custom_zone_uuid_in: Optional[List[str]] = None,
        filter_tile_set_uuid_in: Optional[List[str]] = None,
        filter_detection_validation_status_in: Optional[
            List[DetectionValidationStatus]
        ] = None,
        filter_detection_control_status_in: Optional[
            List[DetectionControlStatus]
        ] = None,
        filter_prescribed: Optional[bool] = None,
        filter_polygon_intersects: Optional[Polygon] = None,
        filter_interface_drawn: Optional[FilterInterfaceDrawn] = None,
        *args,
        **kwargs,
    ):
        # mixin filters

        self.queryset = self._filter_timestamped(
            queryset=self.queryset,
            filter_created_at=filter_created_at,
            filter_updated_at=filter_updated_at,
        )
        self.queryset = self._filter_uuid(
            queryset=self.queryset,
            filter_uuid_in=filter_uuid_in,
            filter_uuid_notin=filter_uuid_notin,
        )

        # custom filters

        self.queryset = self._filter_collectivities(
            queryset=self.queryset,
            filter_collectivity_uuid_in=filter_collectivity_uuid_in,
        )
        self.queryset = self._filter_score(
            queryset=self.queryset,
            filter_score=filter_score,
        )
        self.queryset = self._filter_object_type_uuids(
            filter_object_type_uuid_in=filter_object_type_uuid_in
        )
        self.queryset = self._filter_custom_zone_uuids(
            filter_custom_zone_uuid_in=filter_custom_zone_uuid_in
        )
        self.queryset = self._filter_tile_set_uuids(
            filter_tile_set_uuid_in=filter_tile_set_uuid_in
        )
        self.queryset = self._filter_detection_validation_statuses(
            filter_detection_validation_status_in=filter_detection_validation_status_in
        )
        self.queryset = self._filter_detection_control_statuses(
            filter_detection_control_status_in=filter_detection_control_status_in
        )
        self.queryset = self._filter_prescribed(filter_prescribed=filter_prescribed)
        self.queryset = self._filter_polygon_intersects(
            filter_polygon_intersects=filter_polygon_intersects
        )
        self.queryset = self._filter_interface_drawn(
            filter_interface_drawn=filter_interface_drawn
        )

    @staticmethod
    def _filter_collectivities(
        queryset: QuerySet[Detection],
        filter_collectivity_uuid_in: Optional[List[str]] = None,
    ) -> QuerySet[Detection]:
        if filter_collectivity_uuid_in is not None:
            queryset = queryset.filter(
                geometry__intersects=F("geozone__geometry"),
                geozone__uuid__in=filter_collectivity_uuid_in,
            )

        return queryset

    @staticmethod
    def _filter_score(
        queryset: QuerySet[Detection], filter_score: Optional[NumberFilter] = None
    ) -> QuerySet[Detection]:
        if filter_score is not None:
            queryset = queryset.filter(
                **{f"score__{filter_score.lookup.value}": filter_score.number}
            )

        return queryset

    @staticmethod
    def _filter_object_type_uuids(
        queryset: QuerySet[Detection],
        filter_object_type_uuid_in: Optional[List[str]] = None,
    ) -> QuerySet[Detection]:
        if filter_object_type_uuid_in is not None:
            queryset = queryset.filter(
                detection_object__object_type__uuid__in=filter_object_type_uuid_in
            )

        return queryset

    @staticmethod
    def _filter_custom_zone_uuids(
        queryset: QuerySet[Detection],
        filter_custom_zone_uuid_in: Optional[List[str]] = None,
    ) -> QuerySet[Detection]:
        # TODO: update this method with specific interfaceDrawn

        if filter_custom_zone_uuid_in is not None:
            queryset = queryset.filter(
                geometry__intersects=F("geozone__geometry"),
                geozone__uuid__in=filter_custom_zone_uuid_in,
            )

        return queryset

    @staticmethod
    def _filter_tile_set_uuids(
        queryset: QuerySet[Detection],
        filter_tile_set_uuid_in: Optional[List[str]] = None,
    ) -> QuerySet[Detection]:
        if filter_tile_set_uuid_in is not None:
            queryset = queryset.filter(
                geometry__intersects=F("geozone__geometry"),
                tile_set__uuid__in=filter_tile_set_uuid_in,
            )

        return queryset

    @staticmethod
    def _filter_detection_validation_statuses(
        queryset: QuerySet[Detection],
        filter_detection_validation_status_in: Optional[
            List[DetectionValidationStatus]
        ] = None,
    ) -> QuerySet[Detection]:
        if filter_detection_validation_status_in is not None:
            queryset = queryset.filter(
                detection_data__detection_validation_status=filter_detection_validation_status_in
            )

        return queryset

    @staticmethod
    def _filter_detection_control_statuses(
        queryset: QuerySet[Detection],
        filter_detection_control_status_in: Optional[
            List[DetectionControlStatus]
        ] = None,
    ) -> QuerySet[Detection]:
        if filter_detection_control_status_in is not None:
            queryset = queryset.filter(
                detection_data__detection_control_status=filter_detection_control_status_in
            )

        return queryset

    @staticmethod
    def _filter_prescribed(
        queryset: QuerySet[Detection],
        filter_prescribed: Optional[bool] = None,
    ) -> QuerySet[Detection]:
        if filter_prescribed == True:
            queryset = queryset.filter(
                detection_data__detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED
            )

        if filter_prescribed == False:
            queryset = queryset.filter(
                Q(
                    detection_data__detection_prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED
                )
                | Q(detection_data__detection_prescription_status=None)
            )

        return queryset

    @staticmethod
    def _filter_polygon_intersects(
        queryset: QuerySet[Detection],
        filter_polygon_intersects: Optional[Polygon] = None,
    ) -> QuerySet[Detection]:
        if filter_polygon_intersects:
            queryset = queryset.filter(geometry__intersects=filter_polygon_intersects)

        return queryset

    @staticmethod
    def _filter_interface_drawn(
        queryset: QuerySet[Detection],
        filter_interface_drawn: Optional[FilterInterfaceDrawn] = None,
    ) -> QuerySet[Detection]:
        if filter_interface_drawn is not None:
            queryset = queryset.filter(
                detection_data__detection_control_status=filter_detection_control_status_in
            )

        return queryset
