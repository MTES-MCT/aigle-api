"""Every entry of the collectivity relation tables must be a real, correct Django lookup.

These tables are hand-written strings: a typo or a stale related_name does not raise, it
silently matches zero rows — which reads as "this user may see nothing" rather than as a
bug. This exercises all of them against a known hierarchy.
"""

from django.test import TestCase

from core.constants.collectivity import (
    CODE_FIELD_BY_LEVEL,
    COLLECTIVITY_LEVELS,
    COMMUNE_LOOKUP_BY_LEVEL,
    ZONE_RELATION_LOOKUP,
    model_for_level,
)
from core.models.geo_commune import GeoCommune
from core.models.geo_zone import GeoZoneType
from core.tests.fixtures.geo_data import (
    create_complete_geo_hierarchy,
    create_montpellier_mediterranee_epci,
)


class CollectivityHierarchyTableTests(TestCase):
    def setUp(self):
        self.geo = create_complete_geo_hierarchy()
        self.montpellier = self.geo["communes"]["montpellier"]
        self.beziers = self.geo["communes"]["beziers"]
        self.nimes = self.geo["communes"]["nimes"]
        self.herault = self.geo["departments"]["herault"]
        self.occitanie = self.geo["regions"]["occitanie"]
        self.epci = create_montpellier_mediterranee_epci(
            department=self.herault, communes=[self.montpellier, self.beziers]
        )
        self.zone_by_level = {
            GeoZoneType.COMMUNE: self.montpellier,
            GeoZoneType.EPCI: self.epci,
            GeoZoneType.DEPARTMENT: self.herault,
            GeoZoneType.REGION: self.occitanie,
        }

    def test_every_zone_relation_lookup_resolves_montpellier_perimeter(self):
        """Montpellier, its EPCI, its department and its region are all related to each
        other, so every (from, to) pair must find the counterpart zone."""
        for from_level in COLLECTIVITY_LEVELS:
            for to_level in COLLECTIVITY_LEVELS:
                lookup = ZONE_RELATION_LOOKUP[(from_level, to_level)]
                expected = self.zone_by_level[from_level]
                target = self.zone_by_level[to_level]

                found = (
                    model_for_level(from_level)
                    .objects.filter(**{f"{lookup}__in": [target.id]})
                    .values_list("id", flat=True)
                )

                self.assertIn(
                    expected.id,
                    list(found),
                    f"ZONE_RELATION_LOOKUP[({from_level}, {to_level})] = '{lookup}' "
                    f"did not relate {expected.name} to {target.name}",
                )

    def test_zone_relation_lookups_exclude_unrelated_zones(self):
        """Nîmes is in neither the EPCI nor the Hérault, so no lookup may reach it."""
        for from_level, to_level in [
            (GeoZoneType.COMMUNE, GeoZoneType.EPCI),
            (GeoZoneType.COMMUNE, GeoZoneType.DEPARTMENT),
            (GeoZoneType.EPCI, GeoZoneType.COMMUNE),
            (GeoZoneType.DEPARTMENT, GeoZoneType.COMMUNE),
        ]:
            lookup = ZONE_RELATION_LOOKUP[(from_level, to_level)]
            found = (
                model_for_level(from_level)
                .objects.filter(**{f"{lookup}__in": [self.zone_by_level[to_level].id]})
                .values_list("id", flat=True)
            )
            self.assertNotIn(
                self.nimes.id,
                list(found),
                f"ZONE_RELATION_LOOKUP[({from_level}, {to_level})] leaked Nîmes",
            )

    def test_every_commune_lookup_reaches_the_expected_level(self):
        # A commune that must NOT match, per level. Nîmes shares Montpellier's REGION
        # (Gard is in Occitanie too), so the region case needs a commune from another
        # region entirely.
        outsider_by_level = {
            GeoZoneType.COMMUNE: self.nimes,
            GeoZoneType.EPCI: self.nimes,
            GeoZoneType.DEPARTMENT: self.nimes,
            GeoZoneType.REGION: self.geo["communes"]["paris"],
        }

        for level, lookup in COMMUNE_LOOKUP_BY_LEVEL.items():
            found = list(
                GeoCommune.objects.filter(
                    **{f"{lookup}__in": [self.zone_by_level[level].id]}
                ).values_list("id", flat=True)
            )

            self.assertIn(
                self.montpellier.id,
                found,
                f"COMMUNE_LOOKUP_BY_LEVEL[{level}] = '{lookup}' missed Montpellier",
            )
            outsider = outsider_by_level[level]
            self.assertNotIn(
                outsider.id,
                found,
                f"COMMUNE_LOOKUP_BY_LEVEL[{level}] = '{lookup}' leaked {outsider.name}",
            )

    def test_a_commune_without_an_epci_matches_no_epci_filter(self):
        """GeoCommune.epci is nullable — an orphan commune must simply not match, and
        must never slip in through a NULL."""
        orphan = self.nimes
        self.assertIsNone(orphan.epci_id)

        lookup = COMMUNE_LOOKUP_BY_LEVEL[GeoZoneType.EPCI]
        found = GeoCommune.objects.filter(
            **{f"{lookup}__in": [self.epci.id]}
        ).values_list("id", flat=True)

        self.assertNotIn(orphan.id, list(found))

    def test_code_field_exists_on_every_level_model(self):
        for level in COLLECTIVITY_LEVELS:
            model = model_for_level(level)
            zone = self.zone_by_level[level]
            self.assertTrue(
                model.objects.filter(
                    **{
                        CODE_FIELD_BY_LEVEL[level]: getattr(
                            zone, CODE_FIELD_BY_LEVEL[level]
                        )
                    }
                ).exists(),
                f"CODE_FIELD_BY_LEVEL[{level}] is not a usable column",
            )
