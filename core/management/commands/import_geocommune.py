import json
from typing import Dict, List, TypedDict
from django.core.management.base import BaseCommand
from django.db import IntegrityError

from core.management.commands._common.file import (
    download_json,
)
from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from django.contrib.gis.geos import GEOSGeometry

FILE_JSON_URL = (
    "https://www.data.gouv.fr/fr/datasets/r/857364e9-d288-47b6-be12-6cf1ad05fc8d"
)


class CommuneProperties(TypedDict):
    dep_code: List[str]
    com_code: List[str]
    com_name: List[str]
    geo_shape: Dict


class Command(BaseCommand):
    help = "Import communes to database from JSON"

    def add_arguments(self, parser):
        parser.add_argument("--dpt-insee-codes", action="append", required=False)

    def handle(self, *args, **options):
        dpt_insee_codes = options["dpt_insee_codes"]
        data_communes: List[CommuneProperties] = download_json(FILE_JSON_URL)

        departments = GeoDepartment.objects.filter(
            insee_code__in=[
                data_commune["dep_code"][0]
                for data_commune in data_communes
                if not dpt_insee_codes or data_commune["dep_code"][0] in dpt_insee_codes
            ]
        )
        department_code_department_map = {
            department.insee_code: department for department in departments
        }
        print(f"Starting communes import for departments: {
              ", ".join([dpt.name for dpt in departments])}")

        for data_commune in data_communes:
            name = data_commune["com_name"][0]
            iso_code = data_commune["com_code"][0]
            geometry = GEOSGeometry(json.dumps(data_commune["geo_shape"]["geometry"]))

            department_code = data_commune["dep_code"][0]
            department = department_code_department_map.get(department_code)

            if not department:
                continue

            commune = GeoCommune(
                name=name,
                iso_code=iso_code,
                geometry=geometry,
                department=department,
            )
            try:
                commune.save()
            except IntegrityError:
                pass
