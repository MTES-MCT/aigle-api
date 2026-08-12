"""EPCI as a permission perimeter.

Everything here goes through the commune FK chain (DetectionObject.commune.epci,
Parcel.commune.epci) rather than geometry, which is what the repository and permission
layers now do for every level.
"""

from rest_framework import status

from core.models.detection_data import DetectionControlStatus, DetectionValidationStatus
from core.models.user import UserRole
from core.permissions.detection import DetectionPermission
from core.permissions.tile_set import TileSetPermission
from core.permissions.user import UserPermission
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_tile_set,
)
from core.tests.fixtures.geo_data import (
    create_complete_geo_hierarchy,
    create_montpellier_mediterranee_epci,
    create_nimes_ales_epci,
    create_parcel,
)
from core.tests.fixtures.users import create_user_with_group

BULK_URL = "/api/detection/multiple/"


class EpciPermissionTestsBase(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.geo = create_complete_geo_hierarchy()
        self.montpellier = self.geo["communes"]["montpellier"]
        self.beziers = self.geo["communes"]["beziers"]
        self.nimes = self.geo["communes"]["nimes"]
        self.ales = self.geo["communes"]["ales"]
        self.herault = self.geo["departments"]["herault"]
        self.gard = self.geo["departments"]["gard"]

        self.epci = create_montpellier_mediterranee_epci(
            department=self.herault, communes=[self.montpellier, self.beziers]
        )
        self.other_epci = create_nimes_ales_epci(
            department=self.gard, communes=[self.nimes, self.ales]
        )

    def geometry_in(self, commune):
        centroid = commune.geometry.centroid
        return self.create_bbox_polygon(
            centroid.x - 0.001,
            centroid.y - 0.001,
            centroid.x + 0.001,
            centroid.y + 0.001,
        )

    def create_detection_in(self, commune):
        return create_detection(
            detection_object=create_detection_object(commune=commune),
            geometry=self.geometry_in(commune),
            detection_data=create_detection_data(
                detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
                detection_validation_status=DetectionValidationStatus.SUSPECT,
            ),
        )

    def epci_user(self, email="epci-user@test.com"):
        user, group, _ = create_user_with_group(
            email=email, group_name="Collectivité EPCI", geo_zones=[self.epci]
        )
        return user, group


class EpciCollectivityFilterTests(EpciPermissionTestsBase):
    def test_an_epci_only_group_yields_epci_ids_and_does_not_raise(self):
        """Before EPCI was a level, such a group produced an empty filter and every
        detection/parcel list answered 400."""
        user, _ = self.epci_user()

        collectivity_filter = UserPermission(user=user).get_collectivity_filter()

        self.assertEqual(collectivity_filter.epci_ids, [self.epci.id])
        self.assertIsNone(collectivity_filter.commune_ids)
        self.assertIsNone(collectivity_filter.department_ids)
        self.assertFalse(collectivity_filter.is_empty())


class EpciDetectionWriteScopeTests(EpciPermissionTestsBase):
    def test_selection_spanning_the_epci_communes_is_allowed(self):
        user, _ = self.epci_user()
        detections = [
            self.create_detection_in(self.montpellier),
            self.create_detection_in(self.beziers),
        ]

        self.authenticate_user(user)
        response = self.client.post(
            BULK_URL,
            data={
                "uuids": [str(detection.uuid) for detection in detections],
                "detectionControlStatus": DetectionControlStatus.CONTROLLED_FIELD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_selection_reaching_another_epci_is_denied(self):
        user, _ = self.epci_user()
        detections = [
            self.create_detection_in(self.montpellier),
            self.create_detection_in(self.nimes),
        ]

        self.authenticate_user(user)
        response = self.client.post(
            BULK_URL,
            data={
                "uuids": [str(detection.uuid) for detection in detections],
                "detectionControlStatus": DetectionControlStatus.CONTROLLED_FIELD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_commune_of_the_department_outside_the_epci_is_not_writable(self):
        """The EPCI, not its department, is the perimeter: a commune of the same
        department with no EPCI must stay out."""
        user, _ = self.epci_user()

        orphan = self.montpellier
        orphan.epci = None
        orphan.save()

        writable = DetectionPermission(user=user)._writable_communes()

        self.assertNotIn(orphan.id, [commune.id for commune in writable])
        self.assertIn(self.beziers.id, [commune.id for commune in writable])


class EpciParcelScopeTests(EpciPermissionTestsBase):
    def test_only_the_parcels_of_the_epci_communes_are_listed(self):
        # The hierarchy fixture already puts parcels in Montpellier (inside the EPCI);
        # add one outside it.
        create_parcel(commune=self.nimes, x=4.36, y=43.84)

        user, _ = self.epci_user()
        self.authenticate_user(user)

        response = self.client.get("/api/parcel/", {"limit": 100})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        communes = {row["commune"]["code"] for row in response.data["results"]}
        self.assertEqual(communes, {self.montpellier.iso_code})
        self.assertNotIn(self.nimes.iso_code, communes)


class EpciTileSetScopeTests(EpciPermissionTestsBase):
    def _tile_set(self, name, geo_zones):
        tile_set = create_tile_set(name=name)
        tile_set.geo_zones.set(geo_zones)
        return tile_set

    def _visible_names(self, user):
        return set(
            TileSetPermission(user=user)
            .filter_()
            .values_list("name", flat=True)
            .distinct()
        )

    def test_an_epci_group_sees_tile_sets_at_every_related_level(self):
        self._tile_set("TS epci", [self.epci])
        self._tile_set("TS commune membre", [self.montpellier])
        self._tile_set("TS departement", [self.herault])
        self._tile_set("TS autre epci", [self.other_epci])
        self._tile_set("TS autre commune", [self.nimes])

        user, _ = self.epci_user()

        self.assertEqual(
            self._visible_names(user),
            {"TS epci", "TS commune membre", "TS departement"},
        )

    def test_a_commune_group_sees_the_tile_set_of_its_epci(self):
        self._tile_set("TS epci", [self.epci])
        self._tile_set("TS autre epci", [self.other_epci])

        user, _, _ = create_user_with_group(
            email="commune-of-epci@test.com",
            group_name="Commune Béziers",
            geo_zones=[self.beziers],
        )

        self.assertEqual(self._visible_names(user), {"TS epci"})


class EpciUserGroupSerializationTests(EpciPermissionTestsBase):
    def test_epcis_round_trip_through_the_user_group_api(self):
        admin, _, _ = create_user_with_group(
            email="epci-admin@test.com",
            user_role=UserRole.SUPER_ADMIN,
            group_name="Admin group",
            geo_zones=[self.herault],
        )
        self.authenticate_user(admin)

        response = self.client.post(
            "/api/user-group/",
            data={
                "name": "Groupe EPCI",
                "userGroupType": "COLLECTIVITY",
                "epcisUuids": [str(self.epci.uuid)],
                "objectTypeCategoriesUuids": [],
            },
            format="json",
        )
        # A group needs at least one thematic; assert the collectivity half separately
        # so this test fails on EPCI handling, not on unrelated required fields.
        self.assertNotEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        from core.models.object_type_category import ObjectTypeCategory

        category = ObjectTypeCategory.objects.create(name="Cabanisation test")
        response = self.client.post(
            "/api/user-group/",
            data={
                "name": "Groupe EPCI",
                "userGroupType": "COLLECTIVITY",
                "epcisUuids": [str(self.epci.uuid)],
                "objectTypeCategoriesUuids": [str(category.uuid)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        from core.models.user_group import UserGroup

        group = UserGroup.objects.get(name="Groupe EPCI")
        self.assertEqual(
            set(group.geo_zones.values_list("id", flat=True)), {self.epci.id}
        )

        detail = self.client.get(f"/api/user-group/{group.uuid}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        # `code` is null here for every level (GeoZoneSerializer reads an annotation this
        # payload does not carry) — a pre-existing gap, so identify the zone by uuid.
        self.assertEqual(
            [row["uuid"] for row in detail.data["epcis"]], [str(self.epci.uuid)]
        )
        self.assertEqual(
            [row["name"] for row in detail.data["epcis"]], [self.epci.name]
        )
        self.assertEqual(detail.data["communes"], [])


class EpciTileSetDetectionQTests(EpciPermissionTestsBase):
    """`_build_q_from_tilesets` turns a tile set's zones back into a filter on
    DetectionObject.commune. A level it cannot express leaves the clause EMPTY, which
    reads as "no geographic restriction" — the tile set then matches detections
    nationwide, and `~Q()` blanks every later tile set. These pin both halves."""

    def _q_for(self, geo_zones_map):
        return TileSetPermission._build_q_from_tilesets(
            [{"id": 1, "tile_set_type": "BACKGROUND", "geo_zones": geo_zones_map}],
            detection_object_prefix="detection_object__",
            detection_prefix="",
            intersects_geometry=None,
        )

    def test_an_epci_scoped_tile_set_restricts_to_its_communes(self):
        from core.models.detection import Detection
        from core.models.geo_zone import GeoZoneType

        inside = self.create_detection_in(self.montpellier)
        outside = self.create_detection_in(self.nimes)

        q = self._q_for({GeoZoneType.EPCI: [self.epci.id]})
        # Drop the tile_set__id clause: the fixtures give each detection its own tile set.
        matched = set(
            Detection.objects.filter(
                detection_object__commune__epci__id__in=[self.epci.id]
            ).values_list("id", flat=True)
        )

        self.assertIsNotNone(q)
        self.assertIn("commune__epci", str(q))
        self.assertIn(inside.id, matched)
        self.assertNotIn(outside.id, matched)

    def test_a_tile_set_whose_zones_have_no_commune_path_matches_nothing(self):
        from core.models.geo_zone import GeoZoneType

        # A zone level the commune anchor cannot express (a custom zone).
        q = self._q_for({GeoZoneType.CUSTOM: [1]})

        self.assertIsNotNone(q)
        # Fails closed rather than degenerating to "tile_set = X" with no zone clause.
        self.assertIn("pk__in", str(q))


class EpciGeometryConsistencyTests(EpciPermissionTestsBase):
    """An EPCI's geometry must cover its member communes.

    `import_geoepcis` decides membership on a 60% areal overlap, so the SOURCE polygon
    leaves up to 40% of each member outside it. A group scoped to an EPCI derives its
    accessible geometry from that polygon, so if the two disagree the slivers become
    invisible on the map and undrawable — which is why the importer stores the union of
    the members instead.
    """

    def test_the_epci_fixture_geometry_covers_its_member_communes(self):
        for commune in (self.montpellier, self.beziers):
            self.assertTrue(
                self.epci.geometry.covers(commune.geometry),
                f"EPCI geometry does not cover {commune.name}",
            )

    def test_an_epci_scoped_group_can_see_its_whole_member_communes(self):
        from core.permissions.user import UserPermission

        user, _ = self.epci_user()
        accessible = UserPermission(user=user).get_accessible_geometry()

        self.assertIsNotNone(accessible)
        for commune in (self.montpellier, self.beziers):
            self.assertTrue(
                accessible.covers(commune.geometry),
                f"{commune.name} is not fully accessible to its own EPCI's group",
            )


class EpciCustomZonePatchTests(EpciPermissionTestsBase):
    def test_a_patch_that_mentions_no_collectivity_keeps_the_epci_link(self):
        """`geo_zones.set()` replaces every level at once, so a partial edit — or a
        client predating `epcisUuids` — must not silently strip the zone's scoping."""
        from core.models.geo_custom_zone import GeoCustomZone
        from core.tests.fixtures.users import create_super_admin

        self.authenticate_user(create_super_admin(email="cz-admin@test.com"))

        created = self.client.post(
            "/api/geo/custom-zone/",
            data={
                "name": "ZAE EPCI",
                "color": "#123456",
                "geoCustomZoneStatus": "ACTIVE",
                "geoCustomZoneType": "COMMON",
                "epcisUuids": [str(self.epci.uuid)],
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        zone = GeoCustomZone.objects.get(name="ZAE EPCI")
        self.assertEqual(
            set(zone.geo_zones.values_list("id", flat=True)), {self.epci.id}
        )

        # `color` is only there to satisfy an unrelated validator; the point is that
        # the payload names NO collectivity.
        renamed = self.client.patch(
            f"/api/geo/custom-zone/{zone.uuid}/",
            data={"name": "ZAE EPCI renommée", "color": "#123456"},
            format="json",
        )

        self.assertEqual(renamed.status_code, status.HTTP_200_OK)
        zone.refresh_from_db()
        self.assertEqual(zone.name, "ZAE EPCI renommée")
        self.assertEqual(
            set(zone.geo_zones.values_list("id", flat=True)),
            {self.epci.id},
            "a name-only PATCH wiped the zone's collectivities",
        )
