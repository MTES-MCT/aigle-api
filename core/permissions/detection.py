from typing import List, Optional

from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q, QuerySet

from core.constants.detection import DETECTION_EDIT_PERMISSION_DENIED_MESSAGE
from core.models.detection import Detection
from core.models.detection_object import DetectionObject
from core.models.geo_commune import GeoCommune
from core.models.geo_zone import GeoZoneType
from core.models.user import User
from core.models.user_group import UserGroup, UserGroupRight
from core.permissions.base import BasePermission
from core.permissions.user import UserPermission


class DetectionPermission(
    BasePermission[Detection],
):
    """Write scope of persisted detections: the commune of their DetectionObject must
    be reachable from the user's zones, as everywhere else in the app
    (DetectionRepository._filter_collectivities). Geometry containment is only used as
    a fallback for the legacy rows whose commune is still NULL."""

    def __init__(
        self,
        user: User,
        scoped_user_group: Optional[UserGroup] = None,
    ):
        self.user = user
        self.user_permission = UserPermission(
            user=user, scoped_user_group=scoped_user_group
        )

    @classmethod
    def from_request(cls, request) -> "DetectionPermission":
        from core.permissions.scope import resolve_scoped_user_group

        return cls(
            user=request.user,
            scoped_user_group=resolve_scoped_user_group(request),
        )

    def _writable_communes(self) -> QuerySet[GeoCommune]:
        """Communes reachable from the zones the user holds WRITE on — the same clauses
        as DetectionRepository._filter_collectivities, anchored on GeoCommune."""
        zones = self.user_permission.accessible_geo_zones(UserGroupRight.WRITE)
        communes = zones.filter(geo_zone_type=GeoZoneType.COMMUNE).values("id")
        departments = zones.filter(geo_zone_type=GeoZoneType.DEPARTMENT).values("id")
        regions = zones.filter(geo_zone_type=GeoZoneType.REGION).values("id")

        # Fail closed: with no writable zone every subquery is empty, so no commune
        # matches — never all of them.
        q = Q(id__in=communes)
        q |= Q(department__id__in=departments)
        q |= Q(department__region__id__in=regions)

        return GeoCommune.objects.filter(q)

    def validate_detections_edit_permission(self, detections: List[Detection]) -> None:
        """All or nothing: every detection of the selection must pass."""
        if self.user_permission.is_unrestricted():
            return

        detection_ids = {detection.id for detection in detections}
        if detection_ids:
            # Legacy rows whose commune was never resolved fall back to containment of
            # their OWN geometry: a single zone must contain it, so this is only ever
            # applied per row — never to a geometry merging several detections.
            legacy_q = Q(detection_object__commune__isnull=True) & Exists(
                self.user_permission.accessible_geo_zones(UserGroupRight.WRITE).filter(
                    geometry__contains=OuterRef("geometry")
                )
            )
            # Ids, not counts: a join can duplicate rows and inflate a count into a pass.
            writable_ids = set(
                Detection.objects.filter(id__in=detection_ids)
                .filter(
                    Q(detection_object__commune__in=self._writable_communes())
                    | legacy_q
                )
                .values_list("id", flat=True)
            )
            if not (detection_ids - writable_ids):
                return

        # An empty selection is denied too, as the geometry check it replaces did.
        raise PermissionDenied(DETECTION_EDIT_PERMISSION_DENIED_MESSAGE)

    def validate_detection_object_edit_permission(
        self, detection_object: DetectionObject
    ) -> None:
        """Object-level writes (object type, address, comment, prior letter, and adding
        a detection to the object) are scoped by the object's own commune, so they are
        checked even when it has no detection on a visible tile set."""
        if self.user_permission.is_unrestricted():
            return

        if detection_object.commune_id is not None:
            has_rights = (
                self._writable_communes()
                .filter(id=detection_object.commune_id)
                .exists()
            )
        else:
            # Lazily imported: core.services.detection imports this module.
            from core.services.detection import DetectionService

            # Legacy rows: unlike the per-row check above, an object is judged on its
            # most recent detection only — what the check this replaced did; requiring
            # every detection would deny objects it used to allow.
            detection = DetectionService.get_most_recent_detection(
                detection_object=detection_object
            )
            has_rights = (
                detection is not None
                and self.user_permission.accessible_geo_zones(UserGroupRight.WRITE)
                .filter(geometry__contains=detection.geometry)
                .exists()
            )

        if not has_rights:
            raise PermissionDenied(DETECTION_EDIT_PERMISSION_DENIED_MESSAGE)
