"""The collectivity hierarchy, as data.

Four levels — REGION > DEPARTMENT > EPCI > COMMUNE — related by foreign keys only.
Permission scoping walks these FKs (never a spatial predicate): a detection is reached
through DetectionObject.commune, and the commune's FKs answer every level.

Two tables cover every scoping need in the app:

- ``COMMUNE_LOOKUP_BY_LEVEL`` — from a GeoCommune (or anything with a path to one),
  the lookup that yields the id at a given level. Used wherever rows hang off a commune
  (detections, parcels).
- ``ZONE_RELATION_LOOKUP`` — from a GeoZone subclass at level A, the lookup that yields
  the ids at level B, in both directions. Used where two *zone* selections must be
  compared hierarchically (tile sets, the geo list endpoints).

EPCI is nullable on GeoCommune: a commune outside any EPCI simply matches no EPCI-level
filter, which is the correct answer.
"""

from core.models.geo_zone import GeoZoneType

# Fine -> coarse. Order matters only for display; the lookups below are exhaustive.
COLLECTIVITY_LEVELS = [
    GeoZoneType.COMMUNE,
    GeoZoneType.EPCI,
    GeoZoneType.DEPARTMENT,
    GeoZoneType.REGION,
]

# Anchored on GeoCommune. `<fk>__id` resolves to the local FK column, so the only
# lookup below that costs a join is the region one.
COMMUNE_LOOKUP_BY_LEVEL = {
    GeoZoneType.COMMUNE: "id",
    GeoZoneType.EPCI: "epci__id",
    GeoZoneType.DEPARTMENT: "department__id",
    GeoZoneType.REGION: "department__region__id",
}

# (level of the queryset, level of the ids) -> lookup on that queryset.
ZONE_RELATION_LOOKUP = {
    (GeoZoneType.COMMUNE, GeoZoneType.COMMUNE): "id",
    (GeoZoneType.COMMUNE, GeoZoneType.EPCI): "epci__id",
    (GeoZoneType.COMMUNE, GeoZoneType.DEPARTMENT): "department__id",
    (GeoZoneType.COMMUNE, GeoZoneType.REGION): "department__region__id",
    (GeoZoneType.EPCI, GeoZoneType.COMMUNE): "communes__id",
    (GeoZoneType.EPCI, GeoZoneType.EPCI): "id",
    (GeoZoneType.EPCI, GeoZoneType.DEPARTMENT): "department__id",
    (GeoZoneType.EPCI, GeoZoneType.REGION): "department__region__id",
    (GeoZoneType.DEPARTMENT, GeoZoneType.COMMUNE): "communes__id",
    (GeoZoneType.DEPARTMENT, GeoZoneType.EPCI): "epcis__id",
    (GeoZoneType.DEPARTMENT, GeoZoneType.DEPARTMENT): "id",
    (GeoZoneType.DEPARTMENT, GeoZoneType.REGION): "region__id",
    (GeoZoneType.REGION, GeoZoneType.COMMUNE): "departments__communes__id",
    (GeoZoneType.REGION, GeoZoneType.EPCI): "departments__epcis__id",
    (GeoZoneType.REGION, GeoZoneType.DEPARTMENT): "departments__id",
    (GeoZoneType.REGION, GeoZoneType.REGION): "id",
}


def model_for_level(level: GeoZoneType):
    """The GeoZone subclass backing a collectivity level."""
    from core.models.geo_commune import GeoCommune
    from core.models.geo_department import GeoDepartment
    from core.models.geo_epci import GeoEpci
    from core.models.geo_region import GeoRegion

    return {
        GeoZoneType.COMMUNE: GeoCommune,
        GeoZoneType.EPCI: GeoEpci,
        GeoZoneType.DEPARTMENT: GeoDepartment,
        GeoZoneType.REGION: GeoRegion,
    }[level]


# Field holding the collectivity code, per level.
CODE_FIELD_BY_LEVEL = {
    GeoZoneType.COMMUNE: "iso_code",
    GeoZoneType.EPCI: "siren_code",
    GeoZoneType.DEPARTMENT: "insee_code",
    GeoZoneType.REGION: "insee_code",
}
