from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple
from django.db.models import QuerySet
from django.contrib.gis.db.models.aggregates import Union

from core.models.detection import Detection, DetectionSource
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.models.geo_zone import GeoZone
from core.repository.base import (
    BaseRepository,
    DateRepoFilter,
    NumberRepoFilter,
    TimestampedBaseRepositoryMixin,
    UuidBaseRepositoryMixin,
)
from django.db.models import Q
from django.contrib.gis.geos import Polygon


class RepoFilterInterfaceDrawn(Enum):
    ALL = "ALL"
    INSIDE_SELECTED_ZONES = "INSIDE_SELECTED_ZONES"
    NONE = "NONE"


@dataclass
class RepoFilterCustomZone:
    custom_zone_uuids: List[str]
    interface_drawn: RepoFilterInterfaceDrawn = RepoFilterInterfaceDrawn.NONE


class DetectionRepository(
    BaseRepository[Detection],
    TimestampedBaseRepositoryMixin[Detection],
    UuidBaseRepositoryMixin[Detection],
):
    def _filter(
        self,
        filter_created_at: Optional[DateRepoFilter] = None,
        filter_updated_at: Optional[DateRepoFilter] = None,
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
        filter_collectivity_uuid_in: Optional[List[str]] = None,
        filter_score: Optional[NumberRepoFilter] = None,
        filter_object_type_uuid_in: Optional[List[str]] = None,
        filter_custom_zone: Optional[RepoFilterCustomZone] = None,
        filter_tile_set_uuid_in: Optional[List[str]] = None,
        filter_detection_validation_status_in: Optional[
            List[DetectionValidationStatus]
        ] = None,
        filter_detection_control_status_in: Optional[
            List[DetectionControlStatus]
        ] = None,
        filter_prescribed: Optional[bool] = None,
        filter_polygon_intersects: Optional[Polygon] = None,
        *args,
        **kwargs,
    ) -> Tuple[QuerySet[Detection], Q]:
        # mixin filters

        self.queryset, self.q = self._filter_timestamped(
            queryset=self.queryset,
            q=self.q,
            filter_created_at=filter_created_at,
            filter_updated_at=filter_updated_at,
        )
        self.queryset, self.q = self._filter_uuid(
            queryset=self.queryset,
            q=self.q,
            filter_uuid_in=filter_uuid_in,
            filter_uuid_notin=filter_uuid_notin,
        )

        # custom filters

        self.queryset, self.q = self._filter_collectivities(
            queryset=self.queryset,
            q=self.q,
            filter_collectivity_uuid_in=filter_collectivity_uuid_in,
        )
        self.queryset, self.q = self._filter_score(
            queryset=self.queryset,
            q=self.q,
            filter_score=filter_score,
        )
        self.queryset, self.q = self._filter_object_type_uuids(
            queryset=self.queryset,
            q=self.q,
            filter_object_type_uuid_in=filter_object_type_uuid_in,
        )
        self.queryset, self.q = self._filter_custom_zone(
            queryset=self.queryset, q=self.q, filter_custom_zone=filter_custom_zone
        )
        self.queryset, self.q = self._filter_tile_set_uuids(
            queryset=self.queryset,
            q=self.q,
            filter_tile_set_uuid_in=filter_tile_set_uuid_in,
        )
        self.queryset, self.q = self._filter_detection_validation_statuses(
            queryset=self.queryset,
            q=self.q,
            filter_detection_validation_status_in=filter_detection_validation_status_in,
        )
        self.queryset, self.q = self._filter_detection_control_statuses(
            queryset=self.queryset,
            q=self.q,
            filter_detection_control_status_in=filter_detection_control_status_in,
        )
        self.queryset, self.q = self._filter_prescribed(
            queryset=self.queryset, q=self.q, filter_prescribed=filter_prescribed
        )
        self.queryset, self.q = self._filter_polygon_intersects(
            queryset=self.queryset,
            q=self.q,
            filter_polygon_intersects=filter_polygon_intersects,
        )

        return self.queryset, self.q

    @staticmethod
    def _filter_collectivities(
        queryset: QuerySet[Detection],
        q: Q,
        filter_collectivity_uuid_in: Optional[List[str]] = None,
    ) -> Tuple[QuerySet[Detection], Q]:
        if filter_collectivity_uuid_in is not None:
            collectivity_area = GeoZone.objects.filter(
                uuid__in=filter_collectivity_uuid_in
            ).aggregate(area=Union("geometry"))["area"]

            q_ = Q(geometry__intersects=collectivity_area)
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q

    @staticmethod
    def _filter_score(
        queryset: QuerySet[Detection],
        q: Q,
        filter_score: Optional[NumberRepoFilter] = None,
    ) -> Tuple[QuerySet[Detection], Q]:
        if filter_score is not None:
            q_ = Q(**{f"score__{filter_score.lookup.value}": filter_score.number}) | Q(
                detection_source__in=[
                    DetectionSource.INTERFACE_DRAWN,
                    DetectionSource.INTERFACE_FORCED_VISIBLE,
                ]
            )
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q

    @staticmethod
    def _filter_object_type_uuids(
        queryset: QuerySet[Detection],
        q: Q,
        filter_object_type_uuid_in: Optional[List[str]] = None,
    ) -> Tuple[QuerySet[Detection], Q]:
        if filter_object_type_uuid_in is not None:
            q_ = Q(detection_object__object_type__uuid__in=filter_object_type_uuid_in)
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q

    @staticmethod
    def _filter_custom_zone(
        queryset: QuerySet[Detection],
        q: Q,
        filter_custom_zone: Optional[RepoFilterCustomZone] = None,
    ) -> Tuple[QuerySet[Detection], Q]:
        if filter_custom_zone.custom_zone_uuids:
            if filter_custom_zone.interface_drawn == RepoFilterInterfaceDrawn.ALL:
                q_ = Q(
                    detection_object__geo_custom_zones__uuid__in=filter_custom_zone.custom_zone_uuids
                ) | Q(
                    detection_source__in=[
                        DetectionSource.INTERFACE_DRAWN,
                        DetectionSource.INTERFACE_FORCED_VISIBLE,
                    ]
                )
                queryset = queryset.filter(q_)
                q &= q_

            if filter_custom_zone.interface_drawn in [
                RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES,
                RepoFilterInterfaceDrawn.NONE,
            ]:
                q_ = Q(
                    detection_object__geo_custom_zones__uuid__in=filter_custom_zone.custom_zone_uuids
                )
                queryset = queryset.filter(q_)
                q &= q_

        if filter_custom_zone.interface_drawn == RepoFilterInterfaceDrawn.NONE:
            q_ = ~Q(
                detection_source__in=[
                    DetectionSource.INTERFACE_DRAWN,
                    DetectionSource.INTERFACE_FORCED_VISIBLE,
                ]
            )
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q

    @staticmethod
    def _filter_tile_set_uuids(
        queryset: QuerySet[Detection],
        q: Q,
        filter_tile_set_uuid_in: Optional[List[str]] = None,
    ) -> Tuple[QuerySet[Detection], Q]:
        if filter_tile_set_uuid_in is not None:
            q_ = Q(tile_set__uuid__in=filter_tile_set_uuid_in)
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q

    @staticmethod
    def _filter_detection_validation_statuses(
        queryset: QuerySet[Detection],
        q: Q,
        filter_detection_validation_status_in: Optional[
            List[DetectionValidationStatus]
        ] = None,
    ) -> Tuple[QuerySet[Detection], Q]:
        if filter_detection_validation_status_in is not None:
            q_ = Q(
                detection_data__detection_validation_status__in=filter_detection_validation_status_in
            )
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q

    @staticmethod
    def _filter_detection_control_statuses(
        queryset: QuerySet[Detection],
        q: Q,
        filter_detection_control_status_in: Optional[
            List[DetectionControlStatus]
        ] = None,
    ) -> Tuple[QuerySet[Detection], Q]:
        if filter_detection_control_status_in is not None:
            q_ = Q(
                detection_data__detection_control_status__in=filter_detection_control_status_in
            )
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q

    @staticmethod
    def _filter_prescribed(
        queryset: QuerySet[Detection],
        q: Q,
        filter_prescribed: Optional[bool] = None,
    ) -> Tuple[QuerySet[Detection], Q]:
        if filter_prescribed:
            q_ = Q(
                detection_data__detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED
            )
            queryset = queryset.filter(q_)
            q &= q_

        if filter_prescribed == False:  # noqa: E712
            q_ = Q(
                detection_data__detection_prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED
            ) | Q(detection_data__detection_prescription_status=None)
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q

    @staticmethod
    def _filter_polygon_intersects(
        queryset: QuerySet[Detection],
        q: Q,
        filter_polygon_intersects: Optional[Polygon] = None,
    ) -> Tuple[QuerySet[Detection], Q]:
        if filter_polygon_intersects:
            q_ = Q(geometry__intersects=filter_polygon_intersects)
            queryset = queryset.filter(q_)
            q &= q_

        return queryset, q
