from typing import Optional
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.models.user import User, UserRole
from core.permissions.base import BasePermission
from core.repository.geo_custom_zone import GeoCustomZoneRepository

from django.db.models import Q, QuerySet, Prefetch


class GeoCustomZonePermission(
    BasePermission[GeoCustomZone],
):
    def __init__(
        self,
        user: User,
        initial_queryset: Optional[QuerySet[GeoCustomZone]] = None,
        scoped_user_group=None,
    ):
        self.repository = GeoCustomZoneRepository(initial_queryset=initial_queryset)
        self.user = user
        self.scoped_user_group = scoped_user_group

    def _is_unrestricted(self) -> bool:
        return (
            self.user.user_role == UserRole.SUPER_ADMIN
            and self.scoped_user_group is None
        )

    def _get_prefetch(self, lookup_root: str = ""):
        if self._is_unrestricted():
            geo_custom_zones_prefetch = Prefetch(
                f"{lookup_root}geo_custom_zones",
                queryset=GeoCustomZone.objects.filter(
                    geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
                ),
            )
            geo_custom_zones_category_prefetch = Prefetch(
                f"{lookup_root}geo_custom_zones__geo_custom_zone_category",
                queryset=GeoCustomZoneCategory.objects.filter(
                    geo_custom_zones__geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
                ),
            )
        elif self.scoped_user_group:
            geo_custom_zones_prefetch = Prefetch(
                f"{lookup_root}geo_custom_zones",
                queryset=GeoCustomZone.objects.filter(
                    geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
                    user_groups_custom_geo_zones=self.scoped_user_group,
                ),
            )
            geo_custom_zones_category_prefetch = Prefetch(
                f"{lookup_root}geo_custom_zones__geo_custom_zone_category",
                queryset=GeoCustomZoneCategory.objects.filter(
                    geo_custom_zones__geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
                    geo_custom_zones__user_groups_custom_geo_zones=self.scoped_user_group,
                ),
            )
        else:
            geo_custom_zones_prefetch = Prefetch(
                f"{lookup_root}geo_custom_zones",
                queryset=GeoCustomZone.objects.filter(
                    geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
                    user_groups_custom_geo_zones__user_user_groups__user=self.user.id,
                ),
            )
            geo_custom_zones_category_prefetch = Prefetch(
                f"{lookup_root}geo_custom_zones__geo_custom_zone_category",
                queryset=GeoCustomZoneCategory.objects.filter(
                    geo_custom_zones__geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
                    geo_custom_zones__user_groups_custom_geo_zones__user_user_groups__user=self.user.id,
                ),
            )

        return geo_custom_zones_prefetch, geo_custom_zones_category_prefetch

    def get_detection_object_prefetch(self):
        return self._get_prefetch()

    def get_detection_prefetch(self):
        return self._get_prefetch("detection_object__")

    def get_parcel_prefetch(self):
        return self._get_prefetch()

    def get_geo_custom_zones_q(self, lookup_root: str = "") -> Q:
        q = Q(
            **{
                f"{lookup_root}geo_custom_zones__geo_custom_zone_status": GeoCustomZoneStatus.ACTIVE
            }
        )

        if self.scoped_user_group:
            q &= Q(
                **{
                    f"{lookup_root}geo_custom_zones__user_groups_custom_geo_zones": self.scoped_user_group
                }
            )
        elif not self._is_unrestricted():
            q &= Q(
                **{
                    f"{lookup_root}geo_custom_zones__user_groups_custom_geo_zones__user_user_groups__user": self.user.id
                }
            )

        return q
