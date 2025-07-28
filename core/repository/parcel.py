from dataclasses import dataclass
from typing import List, Optional
from django.db.models import QuerySet
from django.db import models

from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models.functions import Coalesce
from core.models.detection import DetectionSource
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from django.db.models import Count, Prefetch
from core.models.detection_object import DetectionObject
from core.models.parcel import Parcel
from core.repository.base import (
    BaseRepository,
    CollectivityRepoFilter,
    DateRepoFilter,
    NumberRepoFilter,
    TimestampedBaseRepositoryMixin,
    UuidBaseRepositoryMixin,
)
from django.db.models import Q

from core.repository.detection import RepoFilterCustomZone, RepoFilterInterfaceDrawn


@dataclass
class DetectionFilter:
    filter_score: Optional[NumberRepoFilter] = None
    filter_object_type_uuid_in: Optional[List[str]] = None
    filter_custom_zone: Optional[RepoFilterCustomZone] = None
    filter_tile_set_uuid_in: Optional[List[str]] = None
    filter_parcel_uuid_in: Optional[List[str]] = None
    filter_detection_validation_status_in: Optional[List[DetectionValidationStatus]] = (
        None
    )
    filter_detection_control_status_in: Optional[List[DetectionControlStatus]] = None
    filter_prescribed: Optional[bool] = None
    additional_filter: Optional[Q] = None

    def is_empty(self) -> bool:
        return (
            self.filter_score is None
            and self.filter_object_type_uuid_in is None
            and self.filter_custom_zone is None
            and self.filter_tile_set_uuid_in is None
            and self.filter_parcel_uuid_in is None
            and self.filter_detection_validation_status_in is None
            and self.filter_detection_control_status_in is None
            and self.filter_prescribed is None
            and self.additional_filter is None
        )


class ParcelRepository(
    BaseRepository[Parcel],
    TimestampedBaseRepositoryMixin[Parcel],
    UuidBaseRepositoryMixin[Parcel],
):
    def __init__(self, initial_queryset: Optional[QuerySet[Parcel]] = None):
        self.model = Parcel
        self.initial_queryset = (
            initial_queryset if initial_queryset is not None else self.model.objects
        )

    def filter_(
        self,
        queryset: QuerySet[Parcel],
        filter_created_at: Optional[DateRepoFilter] = None,
        filter_updated_at: Optional[DateRepoFilter] = None,
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
        filter_collectivities: Optional[CollectivityRepoFilter] = None,
        filter_commune_uuid_in: Optional[List[str]] = None,
        filter_section_contains: Optional[str] = None,
        filter_section: Optional[str] = None,
        filter_num_parcel_contains: Optional[str] = None,
        filter_num_parcel: Optional[str] = None,
        filter_detection: Optional[DetectionFilter] = None,
        filter_detections_count_gt: Optional[int] = None,
        with_commune: bool = False,
        with_zone_names: bool = False,
        with_detections_count: bool = False,
        with_detections_objects_types: bool = False,
        *args,
        **kwargs,
    ) -> QuerySet[Parcel]:
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

        queryset = self._filter_detection(
            queryset=queryset,
            filter_detection=filter_detection,
        )

        queryset = self._filter_filter_commune_uuid_in(
            queryset=queryset,
            filter_commune_uuid_in=filter_commune_uuid_in,
        )
        queryset = self._filter_section_contains(
            queryset=queryset,
            filter_section_contains=filter_section_contains,
        )
        queryset = self._filter_section(
            queryset=queryset,
            filter_section=filter_section,
        )
        queryset = self._filter_num_parcel_contains(
            queryset=queryset,
            filter_num_parcel_contains=filter_num_parcel_contains,
        )
        queryset = self._filter_num_parcel(
            queryset=queryset,
            filter_num_parcel=filter_num_parcel,
        )

        # annotations

        queryset = self._annotate_commune(
            queryset=queryset,
            with_commune=with_commune,
        )
        queryset = self._annotate_zone_names(
            queryset=queryset,
            with_zone_names=with_zone_names,
        )
        queryset = self._annotate_detections_count(
            queryset=queryset,
            with_detections_count=with_detections_count,
            filter_detections_count_gt=filter_detections_count_gt,
            filter_detection=filter_detection,
        )
        queryset = self._annotate_detections_objects_types(
            queryset=queryset,
            with_detections_objects_types=with_detections_objects_types,
            filter_detection=filter_detection,
        )

        # custom filters

        queryset = self._filter_detections_count_gt(
            queryset=queryset,
            filter_detections_count_gt=filter_detections_count_gt,
        )

        return queryset

    @staticmethod
    def _annotate_commune(
        queryset: QuerySet[Parcel],
        with_commune: bool = False,
    ) -> QuerySet[Parcel]:
        if not with_commune:
            return queryset

        # Use select_related for ForeignKey relationship for better performance
        queryset = queryset.select_related("commune")
        queryset = queryset.defer("commune__geometry")

        return queryset

    @staticmethod
    def _annotate_zone_names(
        queryset: QuerySet[Parcel],
        with_zone_names: bool = False,
    ) -> QuerySet[Parcel]:
        if not with_zone_names:
            return queryset

        queryset = queryset.annotate(
            zone_names=ArrayAgg(
                Coalesce(
                    "geo_custom_zones__geo_custom_zone_category__name",
                    "geo_custom_zones__name",
                ),
                distinct=True,
                filter=models.Q(geo_custom_zones__isnull=False),
            ),
        )

        return queryset

    @staticmethod
    def _build_detection_filter_q(
        filter_detection: Optional[DetectionFilter] = None, prefix: str = ""
    ) -> Q:
        if filter_detection is None or filter_detection.is_empty():
            return Q()

        q = Q()

        # Score filter
        if filter_detection.filter_score is not None:
            score_q = Q(
                Q(
                    **{
                        f"{prefix}detections__score__{filter_detection.filter_score.lookup.value}": filter_detection.filter_score.number
                    }
                )
                | Q(
                    **{
                        f"{prefix}detections__detection_source__in": [
                            DetectionSource.INTERFACE_DRAWN,
                            DetectionSource.INTERFACE_FORCED_VISIBLE,
                        ]
                    }
                )
            )
            q &= score_q

        # Object type filter
        if filter_detection.filter_object_type_uuid_in is not None:
            q &= Q(
                **{
                    f"{prefix}object_type__uuid__in": filter_detection.filter_object_type_uuid_in
                }
            )

        # Custom zone filter
        if filter_detection.filter_custom_zone is not None:
            if filter_detection.filter_custom_zone.custom_zone_uuids:
                if (
                    filter_detection.filter_custom_zone.interface_drawn
                    == RepoFilterInterfaceDrawn.ALL
                ):
                    custom_zone_q = Q(
                        **{
                            f"{prefix}geo_custom_zones__uuid__in": filter_detection.filter_custom_zone.custom_zone_uuids
                        }
                    ) | Q(
                        **{
                            f"{prefix}detections__detection_source__in": [
                                DetectionSource.INTERFACE_DRAWN,
                            ]
                        }
                    )
                    q &= custom_zone_q

                if filter_detection.filter_custom_zone.interface_drawn in [
                    RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES,
                    RepoFilterInterfaceDrawn.NONE,
                ]:
                    q &= Q(
                        **{
                            f"{prefix}geo_custom_zones__uuid__in": filter_detection.filter_custom_zone.custom_zone_uuids
                        }
                    )

            if (
                filter_detection.filter_custom_zone.interface_drawn
                == RepoFilterInterfaceDrawn.NONE
            ):
                q &= ~Q(
                    **{
                        f"{prefix}detections__detection_source": DetectionSource.INTERFACE_DRAWN
                    }
                )

        # Tile set filter
        if filter_detection.filter_tile_set_uuid_in is not None:
            q &= Q(
                **{
                    f"{prefix}detections__tile_set__uuid__in": filter_detection.filter_tile_set_uuid_in
                }
            )

        # Parcel filter
        if filter_detection.filter_parcel_uuid_in is not None:
            q &= Q(
                **{f"{prefix}parcel__uuid__in": filter_detection.filter_parcel_uuid_in}
            )

        # Detection validation status filter
        if filter_detection.filter_detection_validation_status_in is not None:
            q &= Q(
                **{
                    f"{prefix}detections__detection_data__detection_validation_status__in": filter_detection.filter_detection_validation_status_in
                }
            )

        # Detection control status filter
        if filter_detection.filter_detection_control_status_in is not None:
            q &= Q(
                **{
                    f"{prefix}detections__detection_data__detection_control_status__in": filter_detection.filter_detection_control_status_in
                }
            )

        # Prescription filter
        if filter_detection.filter_prescribed is not None:
            if filter_detection.filter_prescribed:
                q &= Q(
                    **{
                        f"{prefix}detections__detection_data__detection_prescription_status": DetectionPrescriptionStatus.PRESCRIBED
                    }
                )
            else:
                q &= Q(
                    Q(
                        **{
                            f"{prefix}detections__detection_data__detection_prescription_status": DetectionPrescriptionStatus.NOT_PRESCRIBED
                        }
                    )
                    | Q(
                        **{
                            f"{prefix}detections__detection_data__detection_prescription_status": None
                        }
                    )
                )

        if filter_detection.additional_filter is not None:
            q &= filter_detection.additional_filter

        return q

    @staticmethod
    def _annotate_detections_count(
        queryset: QuerySet[Parcel],
        with_detections_count: bool = False,
        filter_detections_count_gt: Optional[int] = None,
        filter_detection: Optional[DetectionFilter] = None,
    ) -> QuerySet[Parcel]:
        if not with_detections_count and filter_detections_count_gt is None:
            return queryset

        # Apply detection filter to the count annotation using Parcel context (with detection_objects__ prefix)
        detection_filter_q = ParcelRepository._build_detection_filter_q(
            filter_detection, prefix="detection_objects__"
        )

        queryset = queryset.annotate(
            detections_count=Count(
                "detection_objects__id", filter=detection_filter_q, distinct=True
            )
        )

        return queryset

    @staticmethod
    def _annotate_detections_objects_types(
        queryset: QuerySet[Parcel],
        with_detections_objects_types: bool = False,
        filter_detection: Optional[DetectionFilter] = None,
    ) -> QuerySet[Parcel]:
        if not with_detections_objects_types:
            return queryset

        # Build detection filter for DetectionObject context and apply to prefetch
        detection_filter_q = ParcelRepository._build_detection_object_filter_q(
            filter_detection
        )

        queryset = queryset.prefetch_related(
            Prefetch(
                "detection_objects",
                queryset=DetectionObject.objects.filter(detection_filter_q)
                .select_related("object_type")
                .distinct(),
            )
        )

        return queryset

    @staticmethod
    def _build_detection_object_filter_q(
        filter_detection: Optional[DetectionFilter] = None,
    ) -> Q:
        """
        Build a Q object for filtering DetectionObject querysets.

        This method converts detection filters from Parcel context to DetectionObject context
        by using the correct field relationships:
        - DetectionObject -> Detection (via 'detections' related name)
        - DetectionObject -> ObjectType (direct foreign key)
        - DetectionObject -> GeoCustomZone (many-to-many)

        Args:
            filter_detection: Detection filter with various criteria

        Returns:
            Q object for filtering DetectionObject querysets
        """
        if filter_detection is None or filter_detection.is_empty():
            return Q()

        q = Q()

        # Score filter: Match detections with score >= threshold OR interface-drawn sources
        if filter_detection.filter_score is not None:
            score_q = Q(
                Q(
                    **{
                        f"detections__score__{filter_detection.filter_score.lookup.value}": filter_detection.filter_score.number
                    }
                )
                | Q(
                    detections__detection_source__in=[
                        DetectionSource.INTERFACE_DRAWN,
                        DetectionSource.INTERFACE_FORCED_VISIBLE,
                    ]
                )
            )
            q &= score_q

        # Object type filter: Filter by specific object types
        if filter_detection.filter_object_type_uuid_in is not None:
            q &= Q(object_type__uuid__in=filter_detection.filter_object_type_uuid_in)

        # Custom zone filter: Filter by custom geographic zones
        if filter_detection.filter_custom_zone is not None:
            if filter_detection.filter_custom_zone.custom_zone_uuids:
                # Apply zone filter based on interface drawn preference
                if (
                    filter_detection.filter_custom_zone.interface_drawn
                    == RepoFilterInterfaceDrawn.ALL
                ):
                    q &= Q(
                        geo_custom_zones__uuid__in=filter_detection.filter_custom_zone.custom_zone_uuids
                    )

                elif (
                    filter_detection.filter_custom_zone.interface_drawn
                    == RepoFilterInterfaceDrawn.ONLY_INTERFACE_DRAWN
                ):
                    q &= Q(
                        geo_custom_zones__uuid__in=filter_detection.filter_custom_zone.custom_zone_uuids,
                        detections__detection_source__in=[
                            DetectionSource.INTERFACE_DRAWN,
                            DetectionSource.INTERFACE_FORCED_VISIBLE,
                        ],
                    )

                elif (
                    filter_detection.filter_custom_zone.interface_drawn
                    == RepoFilterInterfaceDrawn.ONLY_NON_INTERFACE_DRAWN
                ):
                    q &= Q(
                        geo_custom_zones__uuid__in=filter_detection.filter_custom_zone.custom_zone_uuids,
                        detections__detection_source=DetectionSource.ANALYSIS,
                    )

                elif filter_detection.filter_custom_zone.interface_drawn in [
                    RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES,
                    RepoFilterInterfaceDrawn.NONE,
                ]:
                    q &= Q(
                        geo_custom_zones__uuid__in=filter_detection.filter_custom_zone.custom_zone_uuids
                    )

            # Apply interface drawn exclusion filter if specified
            if (
                filter_detection.filter_custom_zone.interface_drawn
                == RepoFilterInterfaceDrawn.NONE
            ):
                q &= ~Q(detections__detection_source=DetectionSource.INTERFACE_DRAWN)

        # Parcel filter: Filter by specific parcels
        if filter_detection.filter_parcel_uuid_in is not None:
            q &= Q(parcel__uuid__in=filter_detection.filter_parcel_uuid_in)

        # Detection validation status filter: Filter by validation status
        if filter_detection.filter_detection_validation_status_in is not None:
            q &= Q(
                detections__detection_data__detection_validation_status__in=filter_detection.filter_detection_validation_status_in
            )

        # Detection control status filter: Filter by control status
        if filter_detection.filter_detection_control_status_in is not None:
            q &= Q(
                detections__detection_data__detection_control_status__in=filter_detection.filter_detection_control_status_in
            )

        # Prescription filter: Filter by prescription status
        if filter_detection.filter_prescribed is not None:
            if filter_detection.filter_prescribed:
                q &= Q(
                    detections__detection_data__detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED
                )
            else:
                q &= Q(
                    Q(
                        detections__detection_data__detection_prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED
                    )
                    | Q(
                        detections__detection_data__detection_prescription_status__isnull=True
                    )
                )

        # Additional filter: Apply tile permissions and other complex filters
        if filter_detection.additional_filter is not None:
            # Transform the additional_filter from Parcel context to DetectionObject context
            # by removing the "detection_objects__" prefix from field paths
            transformed_q = ParcelRepository._transform_q_for_detection_object(
                filter_detection.additional_filter
            )
            q &= transformed_q

        return q

    @staticmethod
    def _transform_q_for_detection_object(q_obj: Q) -> Q:
        """
        Transform a Q object from Parcel context to DetectionObject context.

        This method recursively transforms field lookups by removing the 'detection_objects__'
        prefix, allowing filters designed for Parcel querysets to be used with DetectionObject querysets.

        Example transformation:
        - 'detection_objects__detections__score__gte' → 'detections__score__gte'
        - 'detection_objects__object_type__uuid__in' → 'object_type__uuid__in'

        Args:
            q_obj: Q object with field paths in Parcel context

        Returns:
            Q object with field paths adapted for DetectionObject context
        """
        if not q_obj:
            return Q()

        new_q = Q()

        for child in q_obj.children:
            if isinstance(child, Q):
                # Recursively transform nested Q objects
                transformed_child = ParcelRepository._transform_q_for_detection_object(
                    child
                )
                if q_obj.connector == Q.AND:
                    new_q &= transformed_child
                else:
                    new_q |= transformed_child
            elif isinstance(child, tuple) and len(child) == 2:
                # Transform field lookups by removing detection_objects__ prefix
                field_lookup, value = child
                if field_lookup.startswith("detection_objects__"):
                    new_field_lookup = field_lookup[len("detection_objects__") :]
                    new_child = (new_field_lookup, value)
                else:
                    new_child = child

                child_q = Q(new_child)
                if q_obj.connector == Q.AND:
                    new_q &= child_q
                else:
                    new_q |= child_q

        # Preserve negation
        if q_obj.negated:
            new_q.negate()

        return new_q

    @staticmethod
    def _filter_collectivities(
        queryset: QuerySet[Parcel],
        filter_collectivities: Optional[CollectivityRepoFilter] = None,
    ) -> QuerySet[Parcel]:
        if filter_collectivities is None or filter_collectivities.is_empty():
            return queryset

        q = Q()

        if filter_collectivities.commune_ids:
            q |= Q(commune__id__in=filter_collectivities.commune_ids)

        if filter_collectivities.department_ids:
            q |= Q(commune__department__id__in=filter_collectivities.department_ids)

        if filter_collectivities.region_ids:
            q |= Q(commune__department__region__id__in=filter_collectivities.region_ids)

        queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_detection(
        queryset: QuerySet[Parcel],
        filter_detection: Optional[DetectionFilter] = None,
    ) -> QuerySet[Parcel]:
        if filter_detection is None or filter_detection.is_empty():
            return queryset

        # Build a combined Q object to apply all filters at once
        q = Q()

        # Score filter
        if filter_detection.filter_score is not None:
            score_q = Q(
                Q(
                    **{
                        f"detection_objects__detections__score__{filter_detection.filter_score.lookup.value}": filter_detection.filter_score.number
                    }
                )
                | Q(
                    detection_objects__detections__detection_source__in=[
                        DetectionSource.INTERFACE_DRAWN,
                        DetectionSource.INTERFACE_FORCED_VISIBLE,
                    ]
                )
            )
            q &= score_q

        # Object type filter
        if filter_detection.filter_object_type_uuid_in is not None:
            q &= Q(
                detection_objects__object_type__uuid__in=filter_detection.filter_object_type_uuid_in
            )

        # Custom zone filter
        if filter_detection.filter_custom_zone is not None:
            if filter_detection.filter_custom_zone.custom_zone_uuids:
                if (
                    filter_detection.filter_custom_zone.interface_drawn
                    == RepoFilterInterfaceDrawn.ALL
                ):
                    custom_zone_q = Q(
                        detection_objects__geo_custom_zones__uuid__in=filter_detection.filter_custom_zone.custom_zone_uuids
                    ) | Q(
                        detection_objects__detections__detection_source__in=[
                            DetectionSource.INTERFACE_DRAWN,
                        ]
                    )
                    q &= custom_zone_q

                if filter_detection.filter_custom_zone.interface_drawn in [
                    RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES,
                    RepoFilterInterfaceDrawn.NONE,
                ]:
                    q &= Q(
                        detection_objects__geo_custom_zones__uuid__in=filter_detection.filter_custom_zone.custom_zone_uuids
                    )

            if (
                filter_detection.filter_custom_zone.interface_drawn
                == RepoFilterInterfaceDrawn.NONE
            ):
                q &= ~Q(
                    detection_objects__detections__detection_source=DetectionSource.INTERFACE_DRAWN
                )

        # Tile set filter
        if filter_detection.filter_tile_set_uuid_in is not None:
            q &= Q(
                detection_objects__detections__tile_set__uuid__in=filter_detection.filter_tile_set_uuid_in
            )

        # Parcel filter
        if filter_detection.filter_parcel_uuid_in is not None:
            q &= Q(
                detection_objects__parcel__uuid__in=filter_detection.filter_parcel_uuid_in
            )

        # Detection validation status filter
        if filter_detection.filter_detection_validation_status_in is not None:
            q &= Q(
                detection_objects__detections__detection_data__detection_validation_status__in=filter_detection.filter_detection_validation_status_in
            )

        # Detection control status filter
        if filter_detection.filter_detection_control_status_in is not None:
            q &= Q(
                detection_objects__detections__detection_data__detection_control_status__in=filter_detection.filter_detection_control_status_in
            )

        # Prescription filter
        if filter_detection.filter_prescribed is not None:
            if filter_detection.filter_prescribed:
                q &= Q(
                    detection_objects__detections__detection_data__detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED
                )
            else:
                q &= Q(
                    Q(
                        detection_objects__detections__detection_data__detection_prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED
                    )
                    | Q(
                        detection_objects__detections__detection_data__detection_prescription_status=None
                    )
                )

        if filter_detection.additional_filter is not None:
            q &= filter_detection.additional_filter

        if q:
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_filter_commune_uuid_in(
        queryset: QuerySet[Parcel],
        filter_commune_uuid_in: Optional[List[str]] = None,
    ) -> QuerySet[Parcel]:
        if filter_commune_uuid_in is None:
            return queryset

        queryset = queryset.filter(commune__uuid__in=filter_commune_uuid_in)

        return queryset

    @staticmethod
    def _filter_section_contains(
        queryset: QuerySet[Parcel],
        filter_section_contains: Optional[str] = None,
    ) -> QuerySet[Parcel]:
        if filter_section_contains is None:
            return queryset

        queryset = queryset.filter(section__icontains=filter_section_contains)

        return queryset

    @staticmethod
    def _filter_section(
        queryset: QuerySet[Parcel],
        filter_section: Optional[str] = None,
    ) -> QuerySet[Parcel]:
        if filter_section is None:
            return queryset

        queryset = queryset.filter(section=filter_section)

        return queryset

    @staticmethod
    def _filter_num_parcel_contains(
        queryset: QuerySet[Parcel],
        filter_num_parcel_contains: Optional[str] = None,
    ) -> QuerySet[Parcel]:
        if filter_num_parcel_contains is None:
            return queryset

        queryset = queryset.filter(num_parcel__icontains=filter_num_parcel_contains)

        return queryset

    @staticmethod
    def _filter_num_parcel(
        queryset: QuerySet[Parcel],
        filter_num_parcel: Optional[str] = None,
    ) -> QuerySet[Parcel]:
        if filter_num_parcel is None:
            return queryset

        queryset = queryset.filter(num_parcel=filter_num_parcel)

        return queryset

    @staticmethod
    def _filter_detections_count_gt(
        queryset: QuerySet[Parcel],
        filter_detections_count_gt: Optional[int] = None,
    ) -> QuerySet[Parcel]:
        if filter_detections_count_gt is None:
            return queryset

        queryset = queryset.filter(detections_count__gt=filter_detections_count_gt)

        return queryset
