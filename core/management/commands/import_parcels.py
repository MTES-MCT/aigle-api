import json
import tempfile
from typing import Any, Dict, List, Tuple, TypedDict
from django.core.management.base import BaseCommand
from datetime import datetime
import gzip

from core.management.commands._common.file import (
    download_file,
)
from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from django.contrib.gis.geos import GEOSGeometry

from core.models.parcel import Parcel
from core.utils.logs_helpers import log_command_event


class ParcelProperties(TypedDict):
    id: str
    commune: str
    prefixe: str
    section: str
    numero: str
    contenance: int
    arpente: bool
    created: str
    updated: str


class Feature(TypedDict):
    type: "Feature"
    id: str
    geometry: Dict[str, Any]
    properties: ParcelProperties


def get_data_parcels(
    department: str,
) -> Tuple[tempfile.TemporaryDirectory[str], List[Feature]]:
    url = f"https://files.data.gouv.fr/cadastre/etalab-cadastre/2021-02-01/geojson/departements/{department}/cadastre-{department}-parcelles.json.gz"
    file_name = f"cadastre-{department}-parcelles.json.gz"

    temp_dir, file_path = download_file(url=url, file_name=file_name)

    with gzip.open(file_path, "rb") as file:
        file_content = file.read()

    return temp_dir, json.loads(file_content)["features"]


def log_event(info: str):
    log_command_event(command_name="import_parcels", info=info)


class Command(BaseCommand):
    help = "Import parcels to database from JSON"

    def add_arguments(self, parser):
        parser.add_argument("--departments", action="append", required=False)

    def handle(self, *args, **options):
        departments = options["departments"]

        log_event("Starting importing parcels...")

        if not departments:
            log_event(
                "No departments provided, importing parcels for all departments in database"
            )
            departments_data = GeoDepartment.objects.all()
            departments = [department.insee_code for department in departments_data]

        log_event(f"Departments: {', '.join(departments)}")

        for department in departments:
            if not GeoDepartment.objects.filter(insee_code=department).exists():
                log_event(f"Department not found for code: {department}")
                continue

            temp_dir, features = get_data_parcels(department=department)

            communes = GeoCommune.objects.filter(
                iso_code__in=[feature["properties"]["commune"] for feature in features]
            )
            code_commune_commune_map = {com.iso_code: com for com in communes}

            for feature in features:
                properties = feature["properties"]

                id_parcellaire = properties["id"]
                commune_code = properties["commune"]

                commune = code_commune_commune_map.get(commune_code)

                if not commune:
                    log_event(
                        f"Commune not found for code: {
                            commune_code}, skipping parcel: {id_parcellaire}"
                    )
                    continue

                section = properties["section"]
                num_parcel = properties["numero"]
                prefix = properties["prefixe"]
                contenance = properties.get("contenance", 0)
                arpente = properties.get("arpente", False)
                geometry = GEOSGeometry(json.dumps(feature["geometry"]))
                refreshed_at = datetime.strptime(
                    properties["updated"], "%Y-%m-%d"
                ).date()

                parcel = Parcel(
                    id_parcellaire=id_parcellaire,
                    prefix=prefix,
                    section=section,
                    num_parcel=num_parcel,
                    contenance=contenance,
                    arpente=arpente,
                    geometry=geometry,
                    commune=commune,
                    refreshed_at=refreshed_at,
                )
                parcel.save()

            temp_dir.cleanup()
