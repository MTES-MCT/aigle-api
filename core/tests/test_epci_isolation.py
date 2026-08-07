"""Fail-closed properties of the collectivity scoping.

Every assertion here is about what a caller must NOT reach. They are deliberately about
the primitives rather than the endpoints: a scoping bug that fails OPEN shows up as
"one extra row" in an endpoint test and is easy to miss, but it is unambiguous here.
"""

from django.test import TestCase

from core.models.detection import Detection
from core.models.parcel import Parcel
from core.models.tile_set import TileSet
from core.permissions.detection import DetectionPermission
from core.permissions.tile_set import TileSetPermission
from core.permissions.user import UserPermission
from core.repository.base import CollectivityRepoFilter, collectivity_q
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
)
from core.tests.fixtures.users import create_user, create_user_with_group


class CollectivityQFailClosedTests(TestCase):
    def test_a_filter_naming_no_collectivity_matches_nothing(self):
        """`is_empty()` only tests for None, so a filter whose lists are all EMPTY is
        'not empty' yet restricts to nothing. Returning a bare Q() there would read as
        'no restriction' and hand over every row in the country."""
        empty = CollectivityRepoFilter(
            commune_ids=[], epci_ids=[], department_ids=[], region_ids=[]
        )

        self.assertFalse(empty.is_empty())
        self.assertEqual(empty.levels(), [])

        create_complete_geo_hierarchy()
        self.assertGreater(Parcel.objects.count(), 0)
        self.assertEqual(
            Parcel.objects.filter(collectivity_q(empty, "commune__")).count(), 0
        )

    def test_a_populated_filter_restricts_rather_than_excluding_everything(self):
        geo = create_complete_geo_hierarchy()
        montpellier = geo["communes"]["montpellier"]

        q = collectivity_q(
            CollectivityRepoFilter(commune_ids=[montpellier.id]), "commune__"
        )

        self.assertEqual(
            set(Parcel.objects.filter(q).values_list("commune_id", flat=True)),
            {montpellier.id},
        )


class NoGroupUserIsolationTests(TestCase):
    """A user belonging to no group at all must reach nothing — never everything."""

    def setUp(self):
        self.geo = create_complete_geo_hierarchy()
        self.user = create_user(email="orphan@test.com", password="pass123")

    def test_collectivity_filter_refuses_a_user_without_any_zone(self):
        from django.core.exceptions import BadRequest

        with self.assertRaises(BadRequest):
            UserPermission(user=self.user).get_collectivity_filter()

    def test_no_commune_is_writable(self):
        self.assertEqual(
            DetectionPermission(user=self.user)._writable_communes().count(), 0
        )

    def test_no_tile_set_is_visible(self):
        create_tile_set(name="TS")
        self.assertEqual(TileSetPermission(user=self.user).filter_().count(), 0)


class EpciBoundaryTests(TestCase):
    def setUp(self):
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
        self.user, _, _ = create_user_with_group(
            email="epci-boundary@test.com",
            group_name="Collectivité EPCI",
            geo_zones=[self.epci],
        )

    def _detection_in(self, commune):
        return create_detection(
            detection_object=create_detection_object(commune=commune),
            detection_data=create_detection_data(),
        )

    def test_an_epci_group_reaches_exactly_its_member_communes(self):
        for commune in (self.montpellier, self.beziers, self.nimes, self.ales):
            self._detection_in(commune)

        collectivity_filter = UserPermission(user=self.user).get_collectivity_filter()
        reachable = Detection.objects.filter(
            collectivity_q(collectivity_filter, "detection_object__commune__")
        ).values_list("detection_object__commune_id", flat=True)

        self.assertEqual(set(reachable), {self.montpellier.id, self.beziers.id})

    def test_an_epci_group_does_not_reach_its_own_department(self):
        """Scoping to an EPCI must NOT widen to the department containing it — the
        sibling communes of that department are outside the perimeter."""
        orphan = self.geo["communes"]["montpellier"]
        orphan.epci = None
        orphan.save()
        self._detection_in(orphan)

        collectivity_filter = UserPermission(user=self.user).get_collectivity_filter()
        reachable = set(
            Detection.objects.filter(
                collectivity_q(collectivity_filter, "detection_object__commune__")
            ).values_list("detection_object__commune_id", flat=True)
        )

        self.assertNotIn(orphan.id, reachable)

    def test_a_commune_that_left_the_epci_becomes_unreachable(self):
        """Membership is live, not frozen: detaching a commune must revoke access to it
        on the next request (the geo caches are invalidated by import_geoepcis)."""
        detection = self._detection_in(self.beziers)

        def reachable():
            collectivity_filter = UserPermission(
                user=self.user
            ).get_collectivity_filter()
            return set(
                Detection.objects.filter(
                    collectivity_q(collectivity_filter, "detection_object__commune__")
                ).values_list("id", flat=True)
            )

        self.assertIn(detection.id, reachable())

        self.beziers.epci = None
        self.beziers.save()

        self.assertNotIn(detection.id, reachable())

    def test_an_epci_only_tile_set_does_not_leak_outside_the_epci(self):
        """The most dangerous shape: a tile set whose only zone is an EPCI. Its
        per-detection clause must restrict to the EPCI's communes, not degenerate to
        'this tile set' with no geography."""
        from core.models.geo_zone import GeoZoneType

        tile_set = create_tile_set(name="TS epci")
        tile_set.geo_zones.set([self.epci])

        inside = self._detection_in(self.montpellier)
        outside = self._detection_in(self.nimes)
        Detection.objects.filter(id__in=[inside.id, outside.id]).update(
            tile_set=tile_set
        )

        q = TileSetPermission._build_q_from_tilesets(
            [
                {
                    "id": tile_set.id,
                    "tile_set_type": TileSet.objects.get(id=tile_set.id).tile_set_type,
                    "geo_zones": {GeoZoneType.EPCI: [self.epci.id]},
                }
            ],
            detection_object_prefix="detection_object__",
            detection_prefix="",
            intersects_geometry=None,
        )
        matched = set(Detection.objects.filter(q).values_list("id", flat=True))

        self.assertIn(inside.id, matched)
        self.assertNotIn(outside.id, matched)
