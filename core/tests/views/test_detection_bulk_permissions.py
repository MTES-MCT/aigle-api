"""Write scope of detections: it is derived from the commune of their DetectionObject,
so a selection — or a drawn geometry — spanning several communes of the user's perimeter
is editable (the previous per-zone geometry containment check denied it)."""

import datetime

from django.contrib.gis.geos import Point, Polygon
from django.core.exceptions import PermissionDenied
from rest_framework import status

from core.constants.detection import DETECTION_EDIT_PERMISSION_DENIED_MESSAGE
from core.models.detection import Detection, DetectionSource
from core.models.detection_data import DetectionControlStatus, DetectionValidationStatus
from core.models.detection_object import DetectionObject
from core.models.geo_commune import GeoCommune
from core.models.geo_custom_zone import GeoCustomZone
from core.models.user_group import UserGroupRight, UserUserGroup
from core.permissions.detection import DetectionPermission
from core.services.detection import DetectionService
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type,
    create_tile,
    create_tile_set,
)
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy
from core.tests.fixtures.users import (
    create_regular_user,
    create_super_admin,
    create_user_group,
    create_user_with_group,
)

BULK_URL = "/api/detection/multiple/"


class DetectionBulkEditPermissionTestsBase(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.geo = create_complete_geo_hierarchy()
        self.montpellier = self.geo["communes"]["montpellier"]
        self.beziers = self.geo["communes"]["beziers"]
        self.nimes = self.geo["communes"]["nimes"]
        self.herault = self.geo["departments"]["herault"]
        self.gard = self.geo["departments"]["gard"]
        self.occitanie = self.geo["regions"]["occitanie"]

    def geometry_in(self, commune):
        centroid = commune.geometry.centroid
        return self.create_bbox_polygon(
            centroid.x - 0.001,
            centroid.y - 0.001,
            centroid.x + 0.001,
            centroid.y + 0.001,
        )

    def create_detection_in(self, commune, geometry=None):
        if geometry is None:
            geometry = self.geometry_in(commune)

        return create_detection(
            detection_object=create_detection_object(commune=commune),
            geometry=geometry,
            detection_data=create_detection_data(
                detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
                detection_validation_status=DetectionValidationStatus.SUSPECT,
            ),
        )

    def bulk_edit(self, user, detections):
        self.authenticate_user(user)
        return self.client.post(
            BULK_URL,
            data={
                "uuids": [str(detection.uuid) for detection in detections],
                "detectionControlStatus": DetectionControlStatus.CONTROLLED_FIELD,
            },
            format="json",
        )

    def assert_control_status(self, detection, expected):
        detection.detection_data.refresh_from_db()
        self.assertEqual(detection.detection_data.detection_control_status, expected)


class DetectionBulkEditPermissionTests(DetectionBulkEditPermissionTestsBase):
    def test_multi_commune_selection_covered_by_department_is_allowed(self):
        user, _, _ = create_user_with_group(
            email="dept-write@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detections = [
            self.create_detection_in(self.montpellier),
            self.create_detection_in(self.beziers),
        ]

        response = self.bulk_edit(user, detections)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for detection in detections:
            self.assert_control_status(
                detection, DetectionControlStatus.CONTROLLED_FIELD
            )

    def test_multi_commune_selection_covered_by_region_is_allowed(self):
        user, _, _ = create_user_with_group(
            email="region-write@test.com",
            group_name="Occitanie group",
            geo_zones=[self.occitanie],
        )
        detections = [
            self.create_detection_in(self.montpellier),
            self.create_detection_in(self.nimes),
        ]

        response = self.bulk_edit(user, detections)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_multi_commune_selection_covered_by_each_commune_is_allowed(self):
        user, _, _ = create_user_with_group(
            email="communes-write@test.com",
            group_name="Two communes group",
            geo_zones=[self.montpellier, self.beziers],
        )
        detections = [
            self.create_detection_in(self.montpellier),
            self.create_detection_in(self.beziers),
        ]

        response = self.bulk_edit(user, detections)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_selection_with_one_commune_outside_perimeter_is_denied(self):
        user, _, _ = create_user_with_group(
            email="partial-write@test.com",
            group_name="Hérault only group",
            geo_zones=[self.herault],
        )
        inside = self.create_detection_in(self.montpellier)
        outside = self.create_detection_in(self.nimes)

        response = self.bulk_edit(user, [inside, outside])

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["detail"], DETECTION_EDIT_PERMISSION_DENIED_MESSAGE
        )
        # all-or-nothing: the in-perimeter detection must not have been written
        for detection in (inside, outside):
            self.assert_control_status(detection, DetectionControlStatus.NOT_CONTROLLED)

    def test_read_only_membership_is_denied(self):
        user = create_regular_user(email="read-only@test.com")
        group = create_user_group(name="Read only group", geo_zones=[self.herault])
        UserUserGroup.objects.create(
            user=user, user_group=group, user_group_rights=[UserGroupRight.READ]
        )

        response = self.bulk_edit(user, [self.create_detection_in(self.montpellier)])

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["detail"], DETECTION_EDIT_PERMISSION_DENIED_MESSAGE
        )

    def test_another_members_write_on_the_same_group_does_not_grant_write(self):
        """Regression net for UserPermission.accessible_geo_zones: the user and the
        rights conditions must stay inside a SINGLE filter() call. Chained, Django joins
        user_user_groups twice, so the reader below is matched by his own READ
        membership while the WRITE condition is satisfied by ANOTHER member's row on the
        same group — silently granting him write on the whole group perimeter."""
        group = create_user_group(name="Hérault shared group", geo_zones=[self.herault])
        reader = create_regular_user(email="shared-reader@test.com")
        writer = create_regular_user(email="shared-writer@test.com")
        UserUserGroup.objects.create(
            user=reader, user_group=group, user_group_rights=[UserGroupRight.READ]
        )
        UserUserGroup.objects.create(
            user=writer, user_group=group, user_group_rights=[UserGroupRight.WRITE]
        )

        response = self.bulk_edit(reader, [self.create_detection_in(self.montpellier)])

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_read_on_covering_group_and_write_on_another_is_denied(self):
        user = create_regular_user(email="read-a-write-b@test.com")
        group_read = create_user_group(name="Group A read", geo_zones=[self.herault])
        group_write = create_user_group(name="Group B write", geo_zones=[self.gard])
        UserUserGroup.objects.create(
            user=user, user_group=group_read, user_group_rights=[UserGroupRight.READ]
        )
        UserUserGroup.objects.create(
            user=user, user_group=group_write, user_group_rights=[UserGroupRight.WRITE]
        )

        response = self.bulk_edit(user, [self.create_detection_in(self.montpellier)])

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_group_without_geo_zones_is_denied(self):
        user, _, _ = create_user_with_group(
            email="no-zone@test.com", group_name="Empty group"
        )

        response = self.bulk_edit(user, [self.create_detection_in(self.montpellier)])

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["detail"], DETECTION_EDIT_PERMISSION_DENIED_MESSAGE
        )

    def test_group_with_only_a_custom_zone_is_denied(self):
        custom_zone = GeoCustomZone.objects.create(
            name="ZAE test", color="#123456", geometry=self.herault.geometry
        )
        user, _, _ = create_user_with_group(
            email="custom-zone@test.com",
            group_name="Custom zone group",
            geo_zones=[custom_zone],
        )

        response = self.bulk_edit(user, [self.create_detection_in(self.montpellier)])

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_selection_mixing_a_writable_and_an_unknown_uuid_is_denied(self):
        """A uuid matching no row must not be silently dropped: the resolved selection
        would then be a subset of what was asked, and the write a partial one."""
        user, _, _ = create_user_with_group(
            email="unknown-uuid@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detection = self.create_detection_in(self.montpellier)

        self.authenticate_user(user)
        response = self.client.post(
            BULK_URL,
            data={
                "uuids": [
                    str(detection.uuid),
                    "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                ],
                "detectionControlStatus": DetectionControlStatus.CONTROLLED_FIELD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assert_control_status(detection, DetectionControlStatus.NOT_CONTROLLED)

    def test_repeated_uuid_is_not_an_error(self):
        user, _, _ = create_user_with_group(
            email="repeated-uuid@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detection = self.create_detection_in(self.montpellier)

        response = self.bulk_edit(user, [detection, detection])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assert_control_status(detection, DetectionControlStatus.CONTROLLED_FIELD)

    def test_empty_and_unknown_selections_are_denied(self):
        user, _, _ = create_user_with_group(
            email="empty-selection@test.com",
            group_name="Selection group",
            geo_zones=[self.herault],
        )
        detection = self.create_detection_in(self.montpellier)

        self.authenticate_user(user)
        empty_response = self.client.post(
            BULK_URL,
            data={
                "uuids": [],
                "detectionControlStatus": DetectionControlStatus.CONTROLLED_FIELD,
            },
            format="json",
        )
        unknown_response = self.client.post(
            BULK_URL,
            data={
                "uuids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
                "detectionControlStatus": DetectionControlStatus.CONTROLLED_FIELD,
            },
            format="json",
        )

        self.assertEqual(empty_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(unknown_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assert_control_status(detection, DetectionControlStatus.NOT_CONTROLLED)

    def test_unscoped_super_admin_is_allowed(self):
        super_admin = create_super_admin(email="bulk-sa@test.com")
        detections = [
            self.create_detection_in(self.montpellier),
            self.create_detection_in(self.nimes),
        ]

        response = self.bulk_edit(super_admin, detections)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for detection in detections:
            self.assert_control_status(
                detection, DetectionControlStatus.CONTROLLED_FIELD
            )

    def test_commune_is_authoritative_over_geometry(self):
        """Accepted trade-off: a stale commune_id grants, even though the geometry
        sits outside the perimeter. ANDing the geometry check back in would deny any
        detection straddling two communes the user owns — the bug being fixed."""
        user, _, _ = create_user_with_group(
            email="commune-authoritative@test.com",
            group_name="Montpellier group",
            geo_zones=[self.montpellier],
        )
        detection = self.create_detection_in(
            self.montpellier, geometry=Point(4.36, 43.84, srid=4326)
        )

        response = self.bulk_edit(user, [detection])

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class DetectionBulkEditNullCommuneTests(DetectionBulkEditPermissionTestsBase):
    """Legacy rows whose commune was never resolved fall back to the per-detection
    geometry containment check."""

    def setUp(self):
        super().setUp()
        self.user, _, _ = create_user_with_group(
            email="null-commune@test.com",
            group_name="Montpellier group",
            geo_zones=[self.montpellier],
        )

    def test_null_commune_inside_perimeter_is_allowed(self):
        detection = self.create_detection_in(
            None, geometry=Point(3.88, 43.61, srid=4326)
        )

        response = self.bulk_edit(self.user, [detection])

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_null_commune_outside_perimeter_is_denied(self):
        detection = self.create_detection_in(
            None, geometry=Point(4.36, 43.84, srid=4326)
        )

        response = self.bulk_edit(self.user, [detection])

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_mixed_selection_with_null_commune_outside_perimeter_is_denied(self):
        inside = self.create_detection_in(self.montpellier)
        outside = self.create_detection_in(None, geometry=Point(4.36, 43.84, srid=4326))

        response = self.bulk_edit(self.user, [inside, outside])

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assert_control_status(inside, DetectionControlStatus.NOT_CONTROLLED)


class DetectionPermissionQueryCountTests(DetectionBulkEditPermissionTestsBase):
    def test_unrestricted_super_admin_short_circuits_without_query(self):
        super_admin = create_super_admin(email="query-sa@test.com")
        detections = [self.create_detection_in(self.montpellier)]

        with self.assertNumQueries(0):
            DetectionPermission(user=super_admin).validate_detections_edit_permission(
                detections
            )

    def test_query_count_does_not_grow_with_the_selection_size(self):
        user, _, _ = create_user_with_group(
            email="query-count@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        permission = DetectionPermission(user=user)
        few = [self.create_detection_in(self.montpellier) for _ in range(2)]
        many = few + [self.create_detection_in(self.beziers) for _ in range(48)]

        with self.assertNumQueries(1):
            permission.validate_detections_edit_permission(few)

        with self.assertNumQueries(1):
            permission.validate_detections_edit_permission(many)


class DetectionObjectEditPermissionTests(DetectionBulkEditPermissionTestsBase):
    """Object-level writes (object type, address, comment, prior letter) are checked
    even when the object has no detection on a visible tile set."""

    def test_detection_object_without_detection_inside_perimeter_is_allowed(self):
        user, _, _ = create_user_with_group(
            email="object-inside@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detection_object = create_detection_object(commune=self.montpellier)

        DetectionPermission(user=user).validate_detection_object_edit_permission(
            detection_object=detection_object
        )

    def test_detection_object_without_detection_outside_perimeter_is_denied(self):
        user, _, _ = create_user_with_group(
            email="object-outside@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detection_object = create_detection_object(commune=self.nimes)

        with self.assertRaises(PermissionDenied):
            DetectionPermission(user=user).validate_detection_object_edit_permission(
                detection_object=detection_object
            )

    def test_detection_object_without_commune_nor_detection_is_denied(self):
        user, _, _ = create_user_with_group(
            email="object-orphan@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detection_object = create_detection_object()

        with self.assertRaises(PermissionDenied):
            DetectionPermission(user=user).validate_detection_object_edit_permission(
                detection_object=detection_object
            )


class DetectionObjectUpdateRouteTests(DetectionBulkEditPermissionTestsBase):
    def _patch(self, user, detection_object):
        self.authenticate_user(user)
        return self.client.patch(
            f"/api/detection-object/{detection_object.uuid}/",
            data={"comment": "updated"},
            format="json",
        )

    def test_update_denied_outside_perimeter(self):
        user, _, _ = create_user_with_group(
            email="route-outside@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detection = self.create_detection_in(self.nimes)

        response = self._patch(user, detection.detection_object)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_allowed_inside_perimeter(self):
        user, _, _ = create_user_with_group(
            email="route-inside@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detection = self.create_detection_in(self.montpellier)
        detection.detection_data.detection_validation_status = (
            DetectionValidationStatus.SUSPECT
        )
        detection.detection_data.save()

        response = self._patch(user, detection.detection_object)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        detection.detection_object.refresh_from_db()
        self.assertEqual(detection.detection_object.comment, "updated")

    def test_update_allowed_when_only_the_most_recent_detection_is_inside(self):
        """Legacy rows (commune still NULL) fall back to geometry containment on the
        MOST RECENT detection only, as the check this replaced did: an older ML box
        spilling over the commune border must not deny the edit."""
        user, _, _ = create_user_with_group(
            email="route-null-commune@test.com",
            group_name="Montpellier group",
            geo_zones=[self.montpellier],
        )
        detection_object = create_detection_object(commune=None)
        create_detection(
            detection_object=detection_object,
            tile_set=create_tile_set(
                name="Montpellier 2019", date=datetime.date(2019, 1, 1)
            ),
            geometry=self.create_bbox_polygon(3.92, 43.65, 3.94, 43.67),
            detection_data=create_detection_data(
                detection_validation_status=DetectionValidationStatus.SUSPECT
            ),
        )
        create_detection(
            detection_object=detection_object,
            tile_set=create_tile_set(
                name="Montpellier 2024", date=datetime.date(2024, 1, 1)
            ),
            geometry=self.geometry_in(self.montpellier),
            detection_data=create_detection_data(
                detection_validation_status=DetectionValidationStatus.SUSPECT
            ),
        )

        response = self._patch(user, detection_object)

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class DetectionForceVisibleRouteTests(DetectionBulkEditPermissionTestsBase):
    def _force_visible(self, user, uuid):
        self.authenticate_user(user)
        return self.client.patch(f"/api/detection/{uuid}/force-visible/", format="json")

    def test_force_visible_denied_outside_perimeter(self):
        user, _, _ = create_user_with_group(
            email="force-visible-outside@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detection = self.create_detection_in(self.nimes)

        response = self._force_visible(user, detection.uuid)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        detection.refresh_from_db()
        self.assertEqual(detection.detection_source, DetectionSource.ANALYSIS)

    def test_force_visible_allowed_inside_perimeter(self):
        user, _, _ = create_user_with_group(
            email="force-visible-inside@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )
        detection = self.create_detection_in(self.montpellier)

        response = self._force_visible(user, detection.uuid)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        detection.refresh_from_db()
        self.assertEqual(
            detection.detection_source, DetectionSource.INTERFACE_FORCED_VISIBLE
        )

    def test_force_visible_unknown_uuid_returns_404(self):
        user, _, _ = create_user_with_group(
            email="force-visible-unknown@test.com",
            group_name="Hérault group",
            geo_zones=[self.herault],
        )

        response = self._force_visible(user, "3fa85f64-5717-4562-b3fc-2c963f66afa6")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class DetectionCreatePermissionTests(DetectionBulkEditPermissionTestsBase):
    """Creating a detection is scoped by the commune of the DetectionObject it lands on
    — a new one resolved from the drawn geometry's centroid, or a pre-existing one the
    geometry got linked to, whose commune may sit elsewhere entirely."""

    def setUp(self):
        super().setUp()
        # z19 tile containing the drawn geometry's centroid
        create_tile(x=267794, y=191428, z=19)
        self.object_type = create_object_type()
        self.tile_set_2024 = create_tile_set(
            name="Montpellier 2024", date=datetime.date(2024, 1, 1)
        )
        self.tile_set_2024.geo_zones.add(self.montpellier)
        self.tile_set_2019 = create_tile_set(
            name="Montpellier 2019", date=datetime.date(2019, 1, 1)
        )
        self.tile_set_2019.geo_zones.add(self.montpellier)
        self.user, _, _ = create_user_with_group(
            email="create-montpellier@test.com",
            group_name="Montpellier group",
            geo_zones=[self.montpellier],
        )
        self.geometry = Polygon(
            [
                (3.8799, 43.6099),
                (3.8801, 43.6099),
                (3.8801, 43.6101),
                (3.8799, 43.6101),
                (3.8799, 43.6099),
            ],
            srid=4326,
        )

    def existing_object_in(self, commune):
        """An object already carrying a detection the drawn geometry will link to."""
        detection_object = create_detection_object(
            object_type=self.object_type, commune=commune
        )
        create_detection(
            detection_object=detection_object,
            tile_set=self.tile_set_2019,
            geometry=self.geometry,
            detection_data=create_detection_data(),
        )
        return detection_object

    def create_detection_drawn(self, detection_object_uuid=None):
        return DetectionService.create_detection(
            geometry=self.geometry,
            user=self.user,
            tile_set_uuid=str(self.tile_set_2024.uuid),
            detection_object_uuid=detection_object_uuid,
            detection_object_data=None
            if detection_object_uuid
            else {"object_type_uuid": str(self.object_type.uuid)},
        )

    def test_linked_object_outside_perimeter_is_denied(self):
        self.existing_object_in(self.beziers)

        with self.assertRaises(PermissionDenied):
            self.create_detection_drawn()

        self.assertFalse(Detection.objects.filter(tile_set=self.tile_set_2024).exists())

    def test_linked_object_inside_perimeter_is_allowed(self):
        """The legitimate "force visible on another background" flow."""
        detection_object = self.existing_object_in(self.montpellier)

        detection = self.create_detection_drawn()

        self.assertEqual(detection.detection_object_id, detection_object.id)
        self.assertEqual(detection.tile_set_id, self.tile_set_2024.id)

    def test_new_object_inside_perimeter_is_allowed(self):
        detection = self.create_detection_drawn()

        self.assertEqual(detection.detection_object.commune_id, self.montpellier.id)

    def test_denied_creation_leaves_no_detection_object_behind(self):
        """The object is saved (with its custom-zone M2M) before its commune can be
        checked, so the denial must roll the whole creation back."""
        custom_zone = GeoCustomZone.objects.create(
            name="ZAE création",
            color="#123456",
            geometry=self.create_bbox_polygon(3.87, 43.60, 3.89, 43.62),
        )
        # a perimeter granting the drawn geometry but no commune at all
        user, _, _ = create_user_with_group(
            email="create-custom-zone@test.com",
            group_name="Custom zone only group",
            geo_zones=[custom_zone],
        )
        objects_before = DetectionObject.objects.count()

        with self.assertRaises(PermissionDenied):
            DetectionService.create_detection(
                geometry=self.geometry,
                user=user,
                tile_set_uuid=str(self.tile_set_2024.uuid),
                detection_object_data={"object_type_uuid": str(self.object_type.uuid)},
            )

        self.assertEqual(DetectionObject.objects.count(), objects_before)

    def test_caller_supplied_object_outside_perimeter_is_denied(self):
        foreign_object = create_detection_object(
            object_type=self.object_type, commune=self.nimes
        )

        with self.assertRaises(PermissionDenied):
            self.create_detection_drawn(detection_object_uuid=str(foreign_object.uuid))

        self.assertFalse(
            Detection.objects.filter(detection_object=foreign_object).exists()
        )


class DetectionCreateAcrossCommuneBorderTests(DetectionBulkEditPermissionTestsBase):
    """A box drawn across the border shared by two communes of the perimeter: no single
    zone contains it, only the commune it lands on decides."""

    def setUp(self):
        super().setUp()
        self.montpellier_est = GeoCommune.objects.create(
            name="Montpellier Est",
            iso_code="34999",
            department=self.herault,
            # shares Montpellier's eastern edge (lon 3.93)
            geometry=self.create_bbox_polygon(3.93, 43.56, 4.03, 43.66),
        )
        # z19 tile containing the drawn geometry's centroid
        create_tile(x=267866, y=191428, z=19)
        self.object_type = create_object_type()
        self.tile_set = create_tile_set(
            name="Hérault 2024", date=datetime.date(2024, 1, 1)
        )
        self.tile_set.geo_zones.add(self.montpellier, self.montpellier_est)
        # centroid at lon 3.9295 -> lands in Montpellier, east edge spills into the
        # neighbour
        self.geometry = self.create_bbox_polygon(3.9280, 43.6090, 3.9310, 43.6110)

    def create_detection_drawn(self, user):
        return DetectionService.create_detection(
            geometry=self.geometry,
            user=user,
            tile_set_uuid=str(self.tile_set.uuid),
            detection_object_data={"object_type_uuid": str(self.object_type.uuid)},
        )

    def test_straddling_two_owned_communes_is_allowed(self):
        user, _, _ = create_user_with_group(
            email="create-straddling@test.com",
            group_name="Two communes group",
            geo_zones=[self.montpellier, self.montpellier_est],
        )

        detection = self.create_detection_drawn(user)

        self.assertEqual(detection.detection_object.commune_id, self.montpellier.id)

    def test_landing_outside_the_perimeter_is_still_denied(self):
        """The same straddling box, drawn by someone owning only the neighbour: the
        resolved commune is what denies it."""
        user, _, _ = create_user_with_group(
            email="create-straddling-outside@test.com",
            group_name="Neighbour only group",
            geo_zones=[self.montpellier_est],
        )

        with self.assertRaises(PermissionDenied):
            self.create_detection_drawn(user)

        self.assertFalse(Detection.objects.filter(tile_set=self.tile_set).exists())
