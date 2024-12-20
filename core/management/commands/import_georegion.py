import json
from typing import TypedDict
from django.core.management.base import BaseCommand
import shapefile

from core.management.commands._common.file import download_file, extract_zip
from core.models import GeoRegion
from django.contrib.gis.geos import GEOSGeometry

SHP_ZIP_URL = (
    "https://osm13.openstreetmap.fr/~cquest/openfla/export/regions-20180101-shp.zip"
)
SHP_FILE_NAME = "regions-20180101.shp"


class RegionProperties(TypedDict):
    code_insee: str
    nom: str
    nuts2: str
    surf_km2: int
    wikipedia: str


class Command(BaseCommand):
    help = "Import regions to database from SHP"

    def add_arguments(self, parser):
        parser.add_argument("--insee-codes", action="append", required=False)

    def handle(self, *args, **options):
        insee_codes = options["insee_codes"]

        print("Starting importing regions...")

        if insee_codes:
            print(f"Insee codes: {', '.join(insee_codes)}")
        else:
            print("No insee codes provided, importing all regions")

        temp_dir, file_path = download_file(url=SHP_ZIP_URL, file_name="regions.zip")

        extract_folder_path = f"{temp_dir.name}/out"
        extract_zip(file_path=file_path, output_dir=extract_folder_path)

        shape = shapefile.Reader(f"{extract_folder_path}/{SHP_FILE_NAME}")

        for feature in shape.shapeRecords():
            properties: RegionProperties = feature.__geo_interface__["properties"]

            insee_code = properties["code_insee"]

            if insee_codes and insee_code not in insee_codes:
                print(f"Skiping region: {insee_code}")
                continue

            print(f"Inserting region: {insee_codes}")
            geometry = GEOSGeometry(json.dumps(feature.__geo_interface__["geometry"]))
            geometry.transform(2154, 4326)

            region = GeoRegion(
                name=properties["nom"],
                insee_code=properties["code_insee"],
                surface_km2=properties["surf_km2"],
                geometry=geometry,
            )
            region.save()

        temp_dir.cleanup()
