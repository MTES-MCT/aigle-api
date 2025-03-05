import re
from typing import Tuple, TypedDict
from django.core.management.base import BaseCommand
import csv


from core.models.parcel import Parcel

DATE_FORMAT = "dd/MM/yyyy"


class PvRow(TypedDict):
    COMMUNE: str
    CODE_INSEE: str
    REF_CADAST: str
    DATE_PV: str


class Command(BaseCommand):
    help = "Convert a shape to postgis geometry and insert it in database"

    def add_arguments(self, parser):
        parser.add_argument("--pv-csv-path", type=str, required=True)

    def handle(self, *args, **options):
        pv_csv_path = options["pv_csv_path"]
        with open(pv_csv_path) as csv_file:
            reader = csv.DictReader(csv_file, delimiter=",")

            row: PvRow
            for row in reader:
                cadastre_letters, cadastre_numbers = split_letters_numbers(
                    text=row["REF_CADAST"]
                )
                parcel = (
                    Parcel.objects.filter(
                        commune__iso_code=row["CODE_INSEE"],
                        section=cadastre_letters,
                        num_parcel=cadastre_numbers,
                    )
                    .prefetch_related(
                        "detection_objects", "detection_objects__detections"
                    )
                    .first()
                )

                if not parcel:
                    print(
                        f"Parcel not found: code_insee={row["CODE_INSEE"]},ref_cadast={row["REF_CADAST"]} ; search_parameters: section={cadastre_letters},num_parcel={cadastre_numbers}"
                    )
                    continue


# utils


def split_letters_numbers(text: str) -> Tuple[str, str]:
    match = re.match(r"([A-Za-z]+)(\d+)", text)
    if match:
        return match.group(1), match.group(2)
    raise ValueError(f"Invalid format: {text}")
