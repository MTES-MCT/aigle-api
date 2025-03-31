from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
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
    CollectivityRepoFilter,
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
    def __init__(self, initial_queryset: Optional[QuerySet[Detection]] = None):
        self.model = Detection
        self.initial_queryset = initial_queryset or self.model.objects

    def filter_(
        self,
        queryset: QuerySet[Detection],
        filter_created_at: Optional[DateRepoFilter] = None,
        filter_updated_at: Optional[DateRepoFilter] = None,
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
        filter_collectivities: Optional[CollectivityRepoFilter] = None,
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
    ) -> QuerySet[Detection]:
        # mixin filters

        queryset = self._filter_timestamped(
            queryset=queryset,
            filter_created_at=filter_created_at,
            filter_updated_at=filter_updated_at,
        )
        queryset = self._filter_uuid(
            queryset=queryset,
            filter_uuid_in=filter_uuid_in,
            filter_uuid_notin=filter_uuid_notin,
        )

        # custom filters

        queryset = self._filter_collectivities(
            queryset=queryset,
            filter_collectivities=filter_collectivities,
        )
        queryset = self._filter_score(
            queryset=queryset,
            filter_score=filter_score,
        )
        queryset = self._filter_object_type_uuids(
            queryset=queryset,
            filter_object_type_uuid_in=filter_object_type_uuid_in,
        )
        queryset = self._filter_custom_zone(
            queryset=queryset, filter_custom_zone=filter_custom_zone
        )
        queryset = self._filter_tile_set_uuids(
            queryset=queryset,
            filter_tile_set_uuid_in=filter_tile_set_uuid_in,
        )
        queryset = self._filter_detection_validation_statuses(
            queryset=queryset,
            filter_detection_validation_status_in=filter_detection_validation_status_in,
        )
        queryset = self._filter_detection_control_statuses(
            queryset=queryset,
            filter_detection_control_status_in=filter_detection_control_status_in,
        )
        queryset = self._filter_prescribed(
            queryset=queryset, filter_prescribed=filter_prescribed
        )
        queryset = self._filter_polygon_intersects(
            queryset=queryset,
            filter_polygon_intersects=filter_polygon_intersects,
        )

        return queryset

    @staticmethod
    def _filter_collectivities(
        queryset: QuerySet[Detection],
        filter_collectivities: Optional[CollectivityRepoFilter] = None,
    ) -> QuerySet[Detection]:
        if filter_collectivities is not None and not filter_collectivities.is_empty():
            q = Q()

            if filter_collectivities.commune_ids:
                q |= Q(
                    detection_object__parcel__commune__id__in=filter_collectivities.commune_ids
                )

            if filter_collectivities.department_ids:
                q |= Q(
                    detection_object__parcel__commune__department__id__in=filter_collectivities.department_ids
                )

            if filter_collectivities.region_ids:
                q |= Q(
                    detection_object__parcel__commune__department__region__id__in=filter_collectivities.region_ids
                )

            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_score(
        queryset: QuerySet[Detection],
        filter_score: Optional[NumberRepoFilter] = None,
    ) -> QuerySet[Detection]:
        if filter_score is not None:
            q = Q(**{f"score__{filter_score.lookup.value}": filter_score.number}) | Q(
                detection_source__in=[
                    DetectionSource.INTERFACE_DRAWN,
                    DetectionSource.INTERFACE_FORCED_VISIBLE,
                ]
            )
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_object_type_uuids(
        queryset: QuerySet[Detection],
        filter_object_type_uuid_in: Optional[List[str]] = None,
    ) -> QuerySet[Detection]:
        if filter_object_type_uuid_in is not None:
            q = Q(detection_object__object_type__uuid__in=filter_object_type_uuid_in)
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_custom_zone(
        queryset: QuerySet[Detection],
        filter_custom_zone: Optional[RepoFilterCustomZone] = None,
    ) -> QuerySet[Detection]:
        if filter_custom_zone is None:
            return queryset

        if filter_custom_zone.custom_zone_uuids:
            if filter_custom_zone.interface_drawn == RepoFilterInterfaceDrawn.ALL:
                q = Q(
                    detection_object__geo_custom_zones__uuid__in=filter_custom_zone.custom_zone_uuids
                ) | Q(
                    detection_source__in=[
                        DetectionSource.INTERFACE_DRAWN,
                    ]
                )
                queryset = queryset.filter(q)

            if filter_custom_zone.interface_drawn in [
                RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES,
                RepoFilterInterfaceDrawn.NONE,
            ]:
                q = Q(
                    detection_object__geo_custom_zones__uuid__in=filter_custom_zone.custom_zone_uuids
                )
                queryset = queryset.filter(q)

        if filter_custom_zone.interface_drawn == RepoFilterInterfaceDrawn.NONE:
            q = ~Q(
                detection_source__in=[
                    DetectionSource.INTERFACE_DRAWN,
                ]
            )
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_tile_set_uuids(
        queryset: QuerySet[Detection],
        filter_tile_set_uuid_in: Optional[List[str]] = None,
    ) -> QuerySet[Detection]:
        if filter_tile_set_uuid_in is not None:
            q = Q(tile_set__uuid__in=filter_tile_set_uuid_in)
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_detection_validation_statuses(
        queryset: QuerySet[Detection],
        filter_detection_validation_status_in: Optional[
            List[DetectionValidationStatus]
        ] = None,
    ) -> QuerySet[Detection]:
        if filter_detection_validation_status_in is not None:
            q = Q(
                detection_data__detection_validation_status__in=filter_detection_validation_status_in
            )
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_detection_control_statuses(
        queryset: QuerySet[Detection],
        filter_detection_control_status_in: Optional[
            List[DetectionControlStatus]
        ] = None,
    ) -> QuerySet[Detection]:
        if filter_detection_control_status_in is not None:
            q = Q(
                detection_data__detection_control_status__in=filter_detection_control_status_in
            )
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_prescribed(
        queryset: QuerySet[Detection],
        filter_prescribed: Optional[bool] = None,
    ) -> QuerySet[Detection]:
        if filter_prescribed:
            q = Q(
                detection_data__detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED
            )
            queryset = queryset.filter(q)

        if filter_prescribed == False:  # noqa: E712
            q = Q(
                detection_data__detection_prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED
            ) | Q(detection_data__detection_prescription_status=None)
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_polygon_intersects(
        queryset: QuerySet[Detection],
        filter_polygon_intersects: Optional[Polygon] = None,
    ) -> QuerySet[Detection]:
        if filter_polygon_intersects:
            q = Q(geometry__intersects=filter_polygon_intersects)
            queryset = queryset.filter(q)

        return queryset
