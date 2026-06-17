from typing import List, Optional, Dict, Any, TYPE_CHECKING
from django.db.models import Count, Q, F, Sum, Case, When, Value, IntegerField
from django.db.models.query import QuerySet

from core.models.analytic_log import AnalyticLogType
from core.models.detection_data import DetectionControlStatus, DetectionValidationStatus
from core.models.parcel import Parcel
from core.models.user_group import UserGroup
from core.permissions.geo_custom_zone import GeoCustomZonePermission
from core.permissions.user import UserPermission
from core.repository.base import NumberRepoFilter, RepoFilterLookup
from core.repository.parcel import DetectionFilter, ParcelRepository
from core.utils.analytic_log import create_log

if TYPE_CHECKING:
    from core.models.user import User


class ParcelService:
    @staticmethod
    def get_parcel_detail(
        uuid: str,
        user: "User",
        scoped_user_group: Optional[UserGroup] = None,
    ) -> Optional[Parcel]:
        user_permission = UserPermission(user, scoped_user_group=scoped_user_group)
        collectivity_filter = user_permission.get_collectivity_filter()
        object_types_with_status = user_permission.get_user_object_types_with_status()
        filter_geo_custom_zones = GeoCustomZonePermission(
            user=user, scoped_user_group=scoped_user_group
        ).get_geo_custom_zones_q()

        repo = ParcelRepository()
        return repo.get(
            filter_uuid_in=[uuid],
            filter_collectivities=collectivity_filter,
            filter_detection=DetectionFilter(
                filter_score=NumberRepoFilter(
                    lookup=RepoFilterLookup.GTE,
                    number=0.3,
                ),
                filter_detection_validation_status_in=[
                    DetectionValidationStatus.DETECTED_NOT_VERIFIED,
                    DetectionValidationStatus.SUSPECT,
                ],
                filter_object_type_uuid_in=[
                    str(object_type.uuid) for object_type, _ in object_types_with_status
                ],
                filter_detection_control_status_in=[
                    DetectionControlStatus.NOT_CONTROLLED,
                    DetectionControlStatus.CONTROLLED_FIELD,
                    DetectionControlStatus.PRIOR_LETTER_SENT,
                    DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
                    DetectionControlStatus.OBSERVARTION_REPORT_REDACTED,
                    DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
                ],
                filter_prescribed=False,
            ),
            filter_geo_custom_zones=filter_geo_custom_zones,
            with_detail_prefetch=True,
            with_commune=True,
        )

    @staticmethod
    def log_parcel_download(
        user: "User", parcel_uuid: str, detection_object_uuid: Optional[str] = None
    ) -> None:
        create_log(
            user,
            AnalyticLogType.REPORT_DOWNLOAD,
            {
                "parcelUuid": parcel_uuid,
                "detectionObjectUuid": detection_object_uuid,
            },
        )

    @staticmethod
    def get_section_suggestions(
        queryset: QuerySet, section_query: str, limit: int = 10
    ) -> List[str]:
        from django.db.models import Value, Case, When, IntegerField

        queryset = queryset.annotate(
            starts_with_q=Case(
                When(section__istartswith=section_query, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        queryset = queryset.order_by("-starts_with_q").distinct()
        return list(queryset.values_list("section", flat=True)[:limit])

    @staticmethod
    def get_num_parcel_suggestions(
        queryset: QuerySet, num_parcel_query: str, limit: int = 10
    ) -> List[str]:
        queryset = queryset.annotate(
            starts_with_q=Case(
                When(num_parcel__startswith=num_parcel_query, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        queryset = queryset.order_by("-starts_with_q").distinct()
        return [
            str(num_parcel)
            for num_parcel in list(
                queryset.values_list("num_parcel", flat=True)[:limit]
            )
        ]

    @staticmethod
    def get_parcel_overview_statistics(queryset: QuerySet) -> Dict[str, int]:
        queryset = queryset.annotate(
            total_detections=Count("detection_objects__detections__detection_data"),
            not_verified_count=Count(
                "detection_objects__detections__detection_data",
                filter=Q(
                    detection_objects__detections__detection_data__detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED
                ),
            ),
            verified_count=Count(
                "detection_objects__detections__detection_data",
                filter=Q(
                    detection_objects__detections__detection_data__detection_validation_status__in=[
                        DetectionValidationStatus.SUSPECT,
                        DetectionValidationStatus.LEGITIMATE,
                        DetectionValidationStatus.INVALIDATED,
                    ]
                ),
            ),
            not_controlled_count=Count(
                "detection_objects__detections__detection_data",
                filter=Q(
                    detection_objects__detections__detection_data__detection_control_status=DetectionControlStatus.NOT_CONTROLLED
                ),
            ),
            controlled_count=Count(
                "detection_objects__detections__detection_data",
                filter=Q(
                    detection_objects__detections__detection_data__detection_control_status__in=[
                        DetectionControlStatus.CONTROLLED_FIELD,
                        DetectionControlStatus.PRIOR_LETTER_SENT,
                        DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
                        DetectionControlStatus.OBSERVARTION_REPORT_REDACTED,
                        DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
                        DetectionControlStatus.JUGEMENT,
                        DetectionControlStatus.REHABILITATED,
                    ]
                ),
            ),
        )

        result = queryset.aggregate(
            not_verified=Sum(
                Case(
                    When(not_verified_count__gt=0.5 * F("total_detections"), then=1),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            verified=Sum(
                Case(
                    When(verified_count__gte=0.5 * F("total_detections"), then=1),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            not_controlled=Sum(
                Case(
                    When(not_controlled_count__gt=0.5 * F("total_detections"), then=1),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            controlled=Sum(
                Case(
                    When(controlled_count__gte=0.5 * F("total_detections"), then=1),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            total=Count("id"),
        )

        return {
            "not_verified": result["not_verified"] or 0,
            "verified": result["verified"] or 0,
            "not_controlled": result["not_controlled"] or 0,
            "controlled": result["controlled"] or 0,
            "total": result["total"] or 0,
        }

    @staticmethod
    def get_parcel_custom_geo_zones(parcel: Parcel) -> List[Dict[str, Any]]:
        """Relies on prefetched detection_objects when available."""
        from core.serializers.utils.custom_zones import (
            reconciliate_custom_zones_with_sub,
        )

        geo_custom_zones_set = set()
        sub_custom_zones_set = set()

        for detection_obj in parcel.detection_objects.all():
            geo_custom_zones_set.update(detection_obj.geo_custom_zones.all())
            sub_custom_zones_set.update(detection_obj.geo_sub_custom_zones.all())

        return reconciliate_custom_zones_with_sub(
            custom_zones=list(geo_custom_zones_set),
            sub_custom_zones=list(sub_custom_zones_set),
        )

    @staticmethod
    def get_parcel_tile_set_previews_data(
        parcel: Parcel,
        user: "User",
        scoped_user_group: Optional[UserGroup] = None,
    ) -> List[Dict[str, Any]]:
        from core.permissions.tile_set import TileSetPermission

        return TileSetPermission(
            user=user, scoped_user_group=scoped_user_group
        ).get_previews(filter_tile_set_intersects_geometry=parcel.geometry)

    @staticmethod
    def get_parcel_detections_updated_at(parcel: Parcel) -> Optional[Any]:
        updated_at_values = []

        for detection_object in parcel.detection_objects.all():
            for detection in detection_object.detections.all():
                if detection.detection_data.updated_at:
                    updated_at_values.append(detection.detection_data.updated_at)

        return min(updated_at_values) if updated_at_values else None
