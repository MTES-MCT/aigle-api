from datetime import datetime
import re
from typing import Tuple, TypedDict
from django.core.management.base import BaseCommand
import csv


from core.models.detection_data import DetectionControlStatus
from core.models.parcel import Parcel

DATE_FORMAT = "%d/%m/%Y"


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
        csv_file = open(pv_csv_path)
        processed_count = {
            "parcels_found": 0,
            "parcels_not_found": 0,
            "detection_objects_updated": 0,
        }

        parcels_not_found = []

        reader = csv.DictReader(csv_file, delimiter=",")

        row: PvRow
        for row in reader:
            try:
                cadastre_letters, cadastre_numbers = split_letters_numbers(
                    text=row["REF_CADAST"]
                )
            except ValueError:
                print(f"IMPORT PVS: REF_CADAST invalid: {row["REF_CADAST"]}")
                continue

            parcel = (
                Parcel.objects.filter(
                    commune__iso_code=row["CODE_INSEE"],
                    section=cadastre_letters,
                    num_parcel=cadastre_numbers,
                )
                .prefetch_related(
                    "detection_objects",
                    "detection_objects__detections",
                    "detection_objects__detections__detection_data",
                )
                .first()
            )

            if not parcel:
                processed_count["parcels_not_found"] += 1
                parcels_not_found.append([row["CODE_INSEE"], row["REF_CADAST"]])
                print(
                    f"IMPORT PVS: parcel not found: code_insee={row["CODE_INSEE"]},ref_cadast={row["REF_CADAST"]} ; search_parameters: section={cadastre_letters},num_parcel={cadastre_numbers}"
                )
                continue

            processed_count["parcels_found"] += 1
            processed_count["detection_objects_updated"] += (
                parcel.detection_objects.count()
            )

            for detection_object in parcel.detection_objects.all():
                for detection in detection_object.detections.all():
                    detection.detection_data.date_pv = datetime.strptime(
                        row["DATE_PV"], DATE_FORMAT
                    )
                    detection.detection_data.detection_control_status = (
                        DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP
                    )
                    detection.detection_data.save()

            print(
                f"IMPORT PVS: updating detections for parcel: {parcel.id_parcellaire}"
            )

        csv_file.close()

        csv_not_found_filename = f'import_pvs_parcels_not_found-{datetime.today().strftime('%Y-%m-%d-%H:%M:%S')}.csv'

        with open(csv_not_found_filename, "w", newline="") as csvfile:
            csv_not_found_writer = csv.writer(csvfile)
            csv_not_found_writer.writerow(["CODE_INSEE", "REF_CADAST"])

            for row in parcels_not_found:
                csv_not_found_writer.writerow(row)

        print("IMPORT PVS: FINISHED")
        print(f"IMPORT PVS: parcels not found={processed_count['parcels_not_found']}")
        print(f"IMPORT PVS: parcels found={processed_count['parcels_found']}")
        print(
            f"IMPORT PVS: objects updated={processed_count['detection_objects_updated']}"
        )
        print(f"IMPORT PVS: list of not found saved here={csv_not_found_filename}")


# utils


def split_letters_numbers(text: str) -> Tuple[str, str]:
    match = re.match(r"([A-Za-z]+)(\d+)", text)
    if match:
        return match.group(1), match.group(2)
    raise ValueError(f"Invalid format: {text}")
