import json
from typing import List, TypedDict, Union
from django.core.management.base import BaseCommand
import shapefile

from core.management.commands._common.file import (
    download_file,
    download_json,
    extract_zip,
)
from core.models import GeoRegion
from core.models.geo_department import GeoDepartment
from core.utils.logs_helpers import log_command_event
from core.utils.string import normalize
from django.contrib.gis.geos import GEOSGeometry

SHP_ZIP_URL = (
    "http://osm13.openstreetmap.fr/~cquest/openfla/export/departements-20180101-shp.zip"
)
SHP_FILE_NAME = "departements-20180101.shp"

ADDITIONAL_JSON_URL = (
    "https://www.data.gouv.fr/fr/datasets/r/7b4bc207-4e66-49d2-b1a5-26653e369b66"
)


class RegionProperties(TypedDict):
    code_insee: str
    nom: str
    nuts3: str
    surf_km2: int
    wikipedia: str


class AdditionalInfos(TypedDict):
    num_dep: str
    dep_name: str
    region_name: str


def log_event(info: str):
    log_command_event(command_name="import_geodepartment", info=info)


class Command(BaseCommand):
    help = "Import departments to database from SHP"

    def add_arguments(self, parser):
        parser.add_argument("--insee-codes", action="append", required=False)

    def handle(self, *args, **options):
        insee_codes = options["insee_codes"]

        log_event("Starting importing departments...")

        if insee_codes:
            log_event(f"Insee codes: {', '.join(insee_codes)}")
        else:
            log_event("No insee codes provided, importing all departments")

        # shape data
        temp_dir, file_path = download_file(
            url=SHP_ZIP_URL, file_name="departments.zip"
        )

        extract_folder_path = f"{temp_dir.name}/out"
        extract_zip(file_path=file_path, output_dir=extract_folder_path)

        shape = shapefile.Reader(f"{extract_folder_path}/{SHP_FILE_NAME}")

        # additional data
        additional_data: List[AdditionalInfos] = download_json(url=ADDITIONAL_JSON_URL)

        regions = GeoRegion.objects.filter(
            name_normalized__in=[
                normalize(data["region_name"]) for data in additional_data
            ]
        ).all()

        region_name_region_map = {region.name_normalized: region for region in regions}

        department_numero_region_map = {}
        for data_item in additional_data:
            region = region_name_region_map.get(normalize(data_item["region_name"]))

            if not region:
                continue

            department_numero_region_map[process_code_insee(data_item["num_dep"])] = (
                region
            )

        for feature in shape.shapeRecords():
            properties: RegionProperties = feature.__geo_interface__["properties"]

            insee_code = properties["code_insee"]

            if insee_codes and insee_code not in insee_codes:
                continue

            geometry = GEOSGeometry(json.dumps(feature.__geo_interface__["geometry"]))

            code_insee_simplified = process_code_insee(properties["code_insee"])

            department = GeoDepartment(
                name=properties["nom"],
                insee_code=code_insee_simplified,
                surface_km2=properties["surf_km2"],
                geometry=geometry,
                region=department_numero_region_map[code_insee_simplified],
            )

            department.save()

        temp_dir.cleanup()


def process_code_insee(code_insee: Union[str, int]):
    # special case for 69
    return "69" if str(code_insee).startswith("69") else code_insee
