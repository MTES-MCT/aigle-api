from typing import Optional
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.models.user import User, UserRole
from core.permissions.base import BasePermission
from core.repository.geo_custom_zone import GeoCustomZoneRepository

from django.db.models import Q, QuerySet, Prefetch, Func, BooleanField, Value
from django.contrib.gis.db.models import GeometryField
from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.db.models.functions import Intersection


class Covers(Func):
    """ST_Covers(a, b): true when `a` fully covers `b` (no point of b outside a)."""

    function = "ST_Covers"
    arity = 2
    output_field = BooleanField()


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

    @classmethod
    def from_request(
        cls,
        request,
        initial_queryset: Optional[QuerySet[GeoCustomZone]] = None,
    ) -> "GeoCustomZonePermission":
        from core.permissions.scope import resolve_scoped_user_group

        return cls(
            user=request.user,
            initial_queryset=initial_queryset,
            scoped_user_group=resolve_scoped_user_group(request),
        )

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

    def covers_geometry(self, geometry) -> bool:
        """True if the active custom zones accessible to the user cover `geometry`
        (point or polygon). Areas outside every accessible zone à enjeux are "zones
        urbaines" where detections must not be searched, created or displayed. A polygon
        spanning several adjacent accessible zones (inside their union but inside no
        single one) is still allowed; it is simply created with no zone associated (the
        association rule stays single-zone `covers`)."""
        queryset = GeoCustomZone.objects.filter(
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        )

        if self.scoped_user_group:
            queryset = queryset.filter(
                user_groups_custom_geo_zones=self.scoped_user_group
            )
        elif not self._is_unrestricted():
            queryset = queryset.filter(
                user_groups_custom_geo_zones__user_user_groups__user=self.user.id
            )

        # Fast path: a single zone covers it (indexed ST_Covers, GiST). Covers every point
        # and any polygon fully inside one zone — the overwhelming majority of calls.
        if queryset.filter(geometry__covers=geometry).exists():
            return True

        # A point cannot straddle zones, so single-cover is definitive for it.
        if geometry.geom_type == "Point":
            return False

        # Rare: a polygon spanning several adjacent zones. Check ST_Covers against the
        # union of the zones CLIPPED to the polygon (ST_Intersection), so a whole (possibly
        # huge) zone is never unioned — the clipped pieces are bounded by the small polygon.
        # ST_Covers(⋃(zone ∩ P), P) == ST_Covers(⋃zone, P) but stays cheap.
        geom_value = Value(geometry, output_field=GeometryField())
        covered = (
            queryset.filter(geometry__intersects=geometry)
            .aggregate(
                covered=Covers(Union(Intersection("geometry", geom_value)), geom_value)
            )
            .get("covered")
        )
        return bool(covered)

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
