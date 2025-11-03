"""
Geographic test fixtures with real France data.

This module provides functions to create geographic entities for testing:
- Occitanie region
- Hérault and Gard departments
- Montpellier commune
- Parcels in Montpellier area

All geometries use simplified polygons with real-world coordinates (WGS84, SRID=4326).
"""

from django.contrib.gis.geos import Polygon
from core.models import GeoRegion, GeoDepartment, GeoCommune, Parcel


def create_occitanie_region():
    """
    Create Occitanie region with simplified geometry.

    Real data:
    - Name: Occitanie
    - ISO Code: 76
    - Approximate center: 43.6° N, 2.3° E
    """
    # Simplified polygon covering Occitanie region
    coords = [
        (0.0, 42.5),  # SW corner (near Spanish border)
        (5.0, 42.5),  # SE corner (near Italian border)
        (5.0, 45.0),  # NE corner (near Auvergne)
        (0.0, 45.0),  # NW corner (near Aquitaine)
        (0.0, 42.5),  # Close polygon
    ]

    region, _ = GeoRegion.objects.get_or_create(
        insee_code="76",
        defaults={
            "name": "Occitanie",
            "geometry": Polygon(coords, srid=4326),
            "surface_km2": 72724.0,  # Approximate surface area of Occitanie
        },
    )
    return region


def create_herault_department(region=None):
    """
    Create Hérault department with simplified geometry.

    Real data:
    - Name: Hérault
    - ISO Code: 34
    - Capital: Montpellier
    - Approximate bounds: 43.2° to 43.9° N, 2.9° to 3.7° E
    """
    if region is None:
        region = create_occitanie_region()

    # Simplified polygon for Hérault department
    coords = [
        (2.9, 43.2),  # SW corner (Mediterranean coast)
        (3.7, 43.2),  # SE corner
        (3.7, 43.9),  # NE corner
        (2.9, 43.9),  # NW corner
        (2.9, 43.2),  # Close polygon
    ]

    department, _ = GeoDepartment.objects.get_or_create(
        insee_code="34",
        defaults={
            "name": "Hérault",
            "region": region,
            "geometry": Polygon(coords, srid=4326),
            "surface_km2": 6224.0,  # Approximate surface area of Hérault
        },
    )
    return department


def create_gard_department(region=None):
    """
    Create Gard department with simplified geometry.

    Real data:
    - Name: Gard
    - ISO Code: 30
    - Capital: Nîmes
    - Approximate bounds: 43.5° to 44.3° N, 3.5° to 4.5° E
    """
    if region is None:
        region = create_occitanie_region()

    # Simplified polygon for Gard department
    coords = [
        (3.5, 43.5),  # SW corner
        (4.5, 43.5),  # SE corner
        (4.5, 44.3),  # NE corner
        (3.5, 44.3),  # NW corner
        (3.5, 43.5),  # Close polygon
    ]

    department, _ = GeoDepartment.objects.get_or_create(
        insee_code="30",
        defaults={
            "name": "Gard",
            "region": region,
            "geometry": Polygon(coords, srid=4326),
            "surface_km2": 5853.0,  # Approximate surface area of Gard
        },
    )
    return department


def create_montpellier_commune(department=None):
    """
    Create Montpellier commune with simplified geometry.

    Real data:
    - Name: Montpellier
    - ISO Code: 34172
    - Coordinates: ~43.61° N, 3.88° E
    - Area: ~56.88 km²
    """
    if department is None:
        department = create_herault_department()

    # Simplified polygon for Montpellier commune
    # Roughly centered on real Montpellier coordinates
    center_lon, center_lat = 3.88, 43.61
    size = 0.05  # Approximately 5km radius

    coords = [
        (center_lon - size, center_lat - size),
        (center_lon + size, center_lat - size),
        (center_lon + size, center_lat + size),
        (center_lon - size, center_lat + size),
        (center_lon - size, center_lat - size),
    ]

    commune, _ = GeoCommune.objects.get_or_create(
        iso_code="34172",
        defaults={
            "name": "Montpellier",
            "department": department,
            "geometry": Polygon(coords, srid=4326),
        },
    )
    return commune


def create_parcel(commune=None, id_parcellaire="000000", x=None, y=None):
    """
    Create a parcel in Montpellier area.

    Args:
        commune: GeoCommune object (defaults to Montpellier)
        id_parcellaire: Parcel reference number
        x: Longitude (defaults to Montpellier center)
        y: Latitude (defaults to Montpellier center)

    Returns:
        Parcel object
    """
    if commune is None:
        commune = create_montpellier_commune()

    # Default to Montpellier center
    if x is None:
        x = 3.88
    if y is None:
        y = 43.61

    # Create small parcel polygon (~100m x 100m)
    size = 0.001

    coords = [
        (x - size, y - size),
        (x + size, y - size),
        (x + size, y + size),
        (x - size, y + size),
        (x - size, y - size),
    ]

    from django.utils import timezone

    # Extract prefix, section, and num_parcel from id_parcellaire
    # Format is typically: prefix(2) + section(2) + num_parcel
    prefix = id_parcellaire[:2] if len(id_parcellaire) >= 2 else "00"
    section = id_parcellaire[2:4] if len(id_parcellaire) >= 4 else "00"
    num_parcel = int(id_parcellaire[-4:]) if len(id_parcellaire) >= 4 else 0

    parcel, _ = Parcel.objects.get_or_create(
        id_parcellaire=id_parcellaire,
        defaults={
            "commune": commune,
            "geometry": Polygon(coords, srid=4326),
            "prefix": prefix,
            "section": section,
            "num_parcel": num_parcel,
            "contenance": 1000,  # Default area in square meters
            "arpente": False,  # Default: not surveyed
            "refreshed_at": timezone.now(),
        },
    )
    return parcel


def create_montpellier_parcels(commune=None, count=3):
    """
    Create multiple parcels in Montpellier area.

    Args:
        commune: GeoCommune object
        count: Number of parcels to create

    Returns:
        List of Parcel objects
    """
    if commune is None:
        commune = create_montpellier_commune()

    parcels = []
    # Montpellier center coordinates
    base_lon, base_lat = 3.88, 43.61

    for i in range(count):
        # Offset each parcel slightly
        offset = i * 0.01
        parcel = create_parcel(
            commune=commune,
            id_parcellaire=f"34172{i:06d}",
            x=base_lon + offset,
            y=base_lat + offset * 0.5,
        )
        parcels.append(parcel)

    return parcels


def create_complete_geo_hierarchy():
    """
    Create complete geographic hierarchy for testing.

    Returns:
        dict: Dictionary containing all created geographic objects:
            - region: Occitanie
            - herault: Hérault department
            - gard: Gard department
            - montpellier: Montpellier commune
            - parcels: List of parcels in Montpellier
    """
    region = create_occitanie_region()
    herault = create_herault_department(region=region)
    gard = create_gard_department(region=region)
    montpellier = create_montpellier_commune(department=herault)
    parcels = create_montpellier_parcels(commune=montpellier, count=3)

    return {
        "region": region,
        "herault": herault,
        "gard": gard,
        "montpellier": montpellier,
        "parcels": parcels,
    }
