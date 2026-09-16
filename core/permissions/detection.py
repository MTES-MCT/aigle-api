from typing import List, Optional

from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.db.models.lookups import IsNull

from core.constants.collectivity import COMMUNE_LOOKUP_BY_LEVEL
from core.constants.detection import DETECTION_EDIT_PERMISSION_DENIED_MESSAGE
from core.models.detection import Detection
from core.models.detection_object import DetectionObject
from core.models.geo_commune import GeoCommune
from core.models.geo_zone import GeoZone
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

    @staticmethod
    def _communes_from(zones: QuerySet) -> QuerySet[GeoCommune]:
        """Communes reachable from `zones` — the same clauses as
        DetectionRepository._filter_collectivities, anchored on GeoCommune."""
        # Fail closed: with no zone every subquery is empty, so no commune matches —
        # never all of them.
        q = Q()
        for level, lookup in COMMUNE_LOOKUP_BY_LEVEL.items():
            q |= Q(
                **{
                    f"{lookup}__in": zones.filter(geo_zone_type=level).values("id"),
                }
            )

        return GeoCommune.objects.filter(q)

    def _writable_communes(self) -> QuerySet[GeoCommune]:
        """Communes reachable from the zones the user holds WRITE on."""
        return self._communes_from(
            self.user_permission.accessible_geo_zones(UserGroupRight.WRITE)
        )

    def get_readable_objects_q(self, prefix: str = "") -> Optional[Q]:
        """Portée de LECTURE des objets de détection, ancrée sur le DetectionObject
        atteint via `prefix`. None signifie aucune restriction (super-admin non
        impersonné).

        Même règle que les écritures, au droit près : la commune de l'objet doit être
        atteignable depuis les zones de l'utilisateur, et les lignes héritées dont la
        commune n'a jamais été résolue retombent sur la containment géométrique. Sans ce
        repli, un objet éditable (validate_detection_object_edit_permission l'accepte)
        deviendrait illisible, donc inatteignable depuis l'interface.

        Le repli lit ici N'IMPORTE QUELLE détection de l'objet là où l'écriture ne juge
        que la plus récente : c'est un sur-ensemble de ce qui est éditable, et il reste
        borné aux zones de l'utilisateur.
        """
        if self.user_permission.is_unrestricted():
            return None

        # Ids matérialisés : ST_Covers ne porte ainsi que sur les zones de
        # l'utilisateur, et non sur toutes celles dont la bbox contient la détection.
        zone_ids = list(
            self.user_permission.accessible_geo_zones()
            .order_by()
            .values_list("id", flat=True)
            .distinct()
        )
        if not zone_ids:
            return Q(**{f"{prefix}id__in": []})

        zones = GeoZone.objects.filter(id__in=zone_ids)

        # Corrélé ligne par ligne, avec la commune de l'objet parent référencée DANS
        # l'EXISTS : sans cette référence, PostgreSQL en fait un sous-plan haché calculé
        # sur toutes les détections héritées de France, même pour un retrieve (35 à 73 s
        # mesurés sur un volume réaliste, contre ~1 ms ici).
        legacy = Exists(
            Detection.objects.filter(
                IsNull(OuterRef(f"{prefix}commune"), True),
                detection_object_id=OuterRef(f"{prefix}id"),
            ).filter(Exists(zones.filter(geometry__covers=OuterRef("geometry"))))
        )

        return Q(**{f"{prefix}commune__in": self._communes_from(zones)}) | (
            Q(**{f"{prefix}commune__isnull": True}) & legacy
        )

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
