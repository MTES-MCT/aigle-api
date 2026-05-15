from django.contrib.gis.geos import Polygon
from core.models import GeoRegion, GeoDepartment, GeoCommune, Parcel


# --- Regions ---


def create_occitanie_region():
    coords = [
        (0.0, 42.5),
        (5.0, 42.5),
        (5.0, 45.0),
        (0.0, 45.0),
        (0.0, 42.5),
    ]
    region, _ = GeoRegion.objects.get_or_create(
        insee_code="76",
        defaults={
            "name": "Occitanie",
            "geometry": Polygon(coords, srid=4326),
            "surface_km2": 72724,
        },
    )
    return region


def create_ile_de_france_region():
    coords = [
        (1.4, 48.1),
        (3.6, 48.1),
        (3.6, 49.3),
        (1.4, 49.3),
        (1.4, 48.1),
    ]
    region, _ = GeoRegion.objects.get_or_create(
        insee_code="11",
        defaults={
            "name": "Île-de-France",
            "geometry": Polygon(coords, srid=4326),
            "surface_km2": 12012,
        },
    )
    return region


# --- Departments ---


def create_herault_department(region=None):
    if region is None:
        region = create_occitanie_region()
    coords = [
        (2.9, 43.2),
        (3.7, 43.2),
        (3.7, 43.9),
        (2.9, 43.9),
        (2.9, 43.2),
    ]
    department, _ = GeoDepartment.objects.get_or_create(
        insee_code="34",
        defaults={
            "name": "Hérault",
            "region": region,
            "geometry": Polygon(coords, srid=4326),
            "surface_km2": 6224,
        },
    )
    return department


def create_gard_department(region=None):
    if region is None:
        region = create_occitanie_region()
    coords = [
        (3.5, 43.5),
        (4.5, 43.5),
        (4.5, 44.3),
        (3.5, 44.3),
        (3.5, 43.5),
    ]
    department, _ = GeoDepartment.objects.get_or_create(
        insee_code="30",
        defaults={
            "name": "Gard",
            "region": region,
            "geometry": Polygon(coords, srid=4326),
            "surface_km2": 5853,
        },
    )
    return department


def create_paris_department(region=None):
    if region is None:
        region = create_ile_de_france_region()
    coords = [
        (2.25, 48.81),
        (2.42, 48.81),
        (2.42, 48.90),
        (2.25, 48.90),
        (2.25, 48.81),
    ]
    department, _ = GeoDepartment.objects.get_or_create(
        insee_code="75",
        defaults={
            "name": "Paris",
            "region": region,
            "geometry": Polygon(coords, srid=4326),
            "surface_km2": 105,
        },
    )
    return department


def create_hauts_de_seine_department(region=None):
    if region is None:
        region = create_ile_de_france_region()
    coords = [
        (2.14, 48.72),
        (2.34, 48.72),
        (2.34, 48.84),
        (2.14, 48.84),
        (2.14, 48.72),
    ]
    department, _ = GeoDepartment.objects.get_or_create(
        insee_code="92",
        defaults={
            "name": "Hauts-de-Seine",
            "region": region,
            "geometry": Polygon(coords, srid=4326),
            "surface_km2": 176,
        },
    )
    return department


# --- Communes ---


def create_montpellier_commune(department=None):
    if department is None:
        department = create_herault_department()
    center_lon, center_lat = 3.88, 43.61
    size = 0.05
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


def create_beziers_commune(department=None):
    if department is None:
        department = create_herault_department()
    center_lon, center_lat = 3.22, 43.34
    size = 0.04
    coords = [
        (center_lon - size, center_lat - size),
        (center_lon + size, center_lat - size),
        (center_lon + size, center_lat + size),
        (center_lon - size, center_lat + size),
        (center_lon - size, center_lat - size),
    ]
    commune, _ = GeoCommune.objects.get_or_create(
        iso_code="34032",
        defaults={
            "name": "Béziers",
            "department": department,
            "geometry": Polygon(coords, srid=4326),
        },
    )
    return commune


def create_nimes_commune(department=None):
    if department is None:
        department = create_gard_department()
    center_lon, center_lat = 4.36, 43.84
    size = 0.04
    coords = [
        (center_lon - size, center_lat - size),
        (center_lon + size, center_lat - size),
        (center_lon + size, center_lat + size),
        (center_lon - size, center_lat + size),
        (center_lon - size, center_lat - size),
    ]
    commune, _ = GeoCommune.objects.get_or_create(
        iso_code="30189",
        defaults={
            "name": "Nîmes",
            "department": department,
            "geometry": Polygon(coords, srid=4326),
        },
    )
    return commune


def create_ales_commune(department=None):
    if department is None:
        department = create_gard_department()
    center_lon, center_lat = 4.08, 44.12
    size = 0.03
    coords = [
        (center_lon - size, center_lat - size),
        (center_lon + size, center_lat - size),
        (center_lon + size, center_lat + size),
        (center_lon - size, center_lat + size),
        (center_lon - size, center_lat - size),
    ]
    commune, _ = GeoCommune.objects.get_or_create(
        iso_code="30007",
        defaults={
            "name": "Alès",
            "department": department,
            "geometry": Polygon(coords, srid=4326),
        },
    )
    return commune


def create_paris_commune(department=None):
    if department is None:
        department = create_paris_department()
    center_lon, center_lat = 2.35, 48.86
    size = 0.05
    coords = [
        (center_lon - size, center_lat - size),
        (center_lon + size, center_lat - size),
        (center_lon + size, center_lat + size),
        (center_lon - size, center_lat + size),
        (center_lon - size, center_lat - size),
    ]
    commune, _ = GeoCommune.objects.get_or_create(
        iso_code="75056",
        defaults={
            "name": "Paris",
            "department": department,
            "geometry": Polygon(coords, srid=4326),
        },
    )
    return commune


def create_paris_1er_commune(department=None):
    if department is None:
        department = create_paris_department()
    center_lon, center_lat = 2.34, 48.86
    size = 0.01
    coords = [
        (center_lon - size, center_lat - size),
        (center_lon + size, center_lat - size),
        (center_lon + size, center_lat + size),
        (center_lon - size, center_lat + size),
        (center_lon - size, center_lat - size),
    ]
    commune, _ = GeoCommune.objects.get_or_create(
        iso_code="75101",
        defaults={
            "name": "Paris 1er Arrondissement",
            "department": department,
            "geometry": Polygon(coords, srid=4326),
        },
    )
    return commune


def create_boulogne_commune(department=None):
    if department is None:
        department = create_hauts_de_seine_department()
    center_lon, center_lat = 2.24, 48.84
    size = 0.03
    coords = [
        (center_lon - size, center_lat - size),
        (center_lon + size, center_lat - size),
        (center_lon + size, center_lat + size),
        (center_lon - size, center_lat + size),
        (center_lon - size, center_lat - size),
    ]
    commune, _ = GeoCommune.objects.get_or_create(
        iso_code="92012",
        defaults={
            "name": "Boulogne-Billancourt",
            "department": department,
            "geometry": Polygon(coords, srid=4326),
        },
    )
    return commune


def create_nanterre_commune(department=None):
    if department is None:
        department = create_hauts_de_seine_department()
    center_lon, center_lat = 2.20, 48.89
    size = 0.03
    coords = [
        (center_lon - size, center_lat - size),
        (center_lon + size, center_lat - size),
        (center_lon + size, center_lat + size),
        (center_lon - size, center_lat + size),
        (center_lon - size, center_lat - size),
    ]
    commune, _ = GeoCommune.objects.get_or_create(
        iso_code="92050",
        defaults={
            "name": "Nanterre",
            "department": department,
            "geometry": Polygon(coords, srid=4326),
        },
    )
    return commune


# --- Parcels ---


def create_parcel(commune=None, id_parcellaire="000000", x=None, y=None):
    if commune is None:
        commune = create_montpellier_commune()

    if x is None:
        x = 3.88
    if y is None:
        y = 43.61

    size = 0.001
    coords = [
        (x - size, y - size),
        (x + size, y - size),
        (x + size, y + size),
        (x - size, y + size),
        (x - size, y - size),
    ]

    from django.utils import timezone

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
            "contenance": 1000,
            "arpente": False,
            "refreshed_at": timezone.now(),
        },
    )
    return parcel


def create_montpellier_parcels(commune=None, count=3):
    if commune is None:
        commune = create_montpellier_commune()

    parcels = []
    base_lon, base_lat = 3.88, 43.61

    for i in range(count):
        offset = i * 0.01
        parcel = create_parcel(
            commune=commune,
            id_parcellaire=f"34172{i:06d}",
            x=base_lon + offset,
            y=base_lat + offset * 0.5,
        )
        parcels.append(parcel)

    return parcels


# --- Complete hierarchy ---


def create_complete_geo_hierarchy():
    occitanie = create_occitanie_region()
    ile_de_france = create_ile_de_france_region()

    herault = create_herault_department(region=occitanie)
    gard = create_gard_department(region=occitanie)
    paris_dept = create_paris_department(region=ile_de_france)
    hauts_de_seine = create_hauts_de_seine_department(region=ile_de_france)

    montpellier = create_montpellier_commune(department=herault)
    beziers = create_beziers_commune(department=herault)
    nimes = create_nimes_commune(department=gard)
    ales = create_ales_commune(department=gard)
    paris = create_paris_commune(department=paris_dept)
    paris_1er = create_paris_1er_commune(department=paris_dept)
    boulogne = create_boulogne_commune(department=hauts_de_seine)
    nanterre = create_nanterre_commune(department=hauts_de_seine)

    parcels = create_montpellier_parcels(commune=montpellier, count=3)

    return {
        "regions": {
            "occitanie": occitanie,
            "ile_de_france": ile_de_france,
        },
        "departments": {
            "herault": herault,
            "gard": gard,
            "paris": paris_dept,
            "hauts_de_seine": hauts_de_seine,
        },
        "communes": {
            "montpellier": montpellier,
            "beziers": beziers,
            "nimes": nimes,
            "ales": ales,
            "paris": paris,
            "paris_1er": paris_1er,
            "boulogne": boulogne,
            "nanterre": nanterre,
        },
        "parcels": parcels,
    }
