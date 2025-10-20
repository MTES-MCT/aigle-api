from collections import defaultdict
import csv
from dataclasses import dataclass
from functools import reduce
from typing import List, Literal, Optional, Set, Tuple, TypedDict
from django.core.management.base import BaseCommand

from core.models.detection_authorization import DetectionAuthorization
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionValidationStatus,
    DetectionValidationStatusChangeReason,
)
from core.models.parcel import Parcel
from core.utils.logs_helpers import log_command_event
from operator import or_
from django.db.models import Q, Count, Prefetch
from core.models.detection_object import DetectionObject
from core.models.detection import Detection

BATCH_SIZE = 100
BULK_UPDATE_BATCH_SIZE = 1000


def log_event(info: str):
    log_command_event(command_name="import_sitadel", info=info)


class DataInputWithoutParcels(TypedDict):
    DEP_CODE: str
    COMM: str
    TYPE_DAU: Literal[
        "PC", "DP", "PA"
    ]  # PC = Permis de construire, DP = Déclaration Préalable
    NUM_DAU: str
    ETAT_DAU: Literal[
        "2", "4", "5", "6"
    ]  # 2 = Autorisé, 4 = Annulé, 5 = Commencé, 6 = Terminé
    DATE_REELLE_AUTORISATION: str
    DPC_DERN: str  # date (mois) (DPC) de dernière mise à jour des données


class DataInputRow(DataInputWithoutParcels):
    SEC_CADASTRE1: str
    NUM_CADASTRE1: str
    SEC_CADASTRE2: str
    NUM_CADASTRE2: str
    SEC_CADASTRE3: str
    NUM_CADASTRE3: str


@dataclass
class DataParcel:
    section: str
    num: int


@dataclass
class DataOutputRow:
    data_parcels: List[DataParcel]
    data_input: DataInputWithoutParcels
    parcels: Optional[List[Parcel]] = None


class Command(BaseCommand):
    help = "Import Sitadel file"
    dpt_detection_objects_ids_updated_map = defaultdict(set)
    dpt_parcels_ids_updated_map = defaultdict(set)

    def add_arguments(self, parser):
        parser.add_argument("--file-csv-path", type=str, required=True)
        parser.add_argument("--persist-data", type=bool, default=False)
        parser.add_argument("--filter-coms", action="append", required=False)

    def handle(self, *args, **options):
        file_csv_path = options["file_csv_path"]
        persist_data = options["persist_data"]
        filter_coms = options["filter_coms"]

        file_csv = open(file_csv_path, mode="r")
        file_csv_reader = csv.DictReader(file_csv)

        while True:
            csv_data = self.extract_data_from_csv(
                file_csv_reader=file_csv_reader, filter_coms=filter_coms
            )

            if not csv_data:
                break

            parcels = self.get_parcels(csv_data)

            csv_data = self.reconcile_parcels(csv_data, parcels)
            self.update_database(data=csv_data, persist_data=persist_data)

            self.log()

    @staticmethod
    def extract_data_from_csv(
        file_csv_reader: csv.DictReader, filter_coms: Optional[List[str]]
    ) -> List[DataOutputRow]:
        data = []

        for row in file_csv_reader:
            # état = Annulé
            if row["ETAT_DAU"] == "4":
                continue

            if filter_coms and row["COMM"] not in filter_coms:
                continue

            data_output = get_data_output(row)

            if not data_output.data_parcels:
                continue

            data.append(data_output)

            if len(data) == BATCH_SIZE:
                break

        return data

    @staticmethod
    def get_parcels(data: List[DataOutputRow]):
        # we extract unique parcels to simplify sql request
        # structure: Set[(commune, section, num)]
        unique_parcels: Set[Tuple[str, str, int]] = set()

        for item in data:
            unique_parcels.update(
                (item.data_input["COMM"], parcel.section, parcel.num)
                for parcel in item.data_parcels
            )

        wheres: List[Q] = [
            Q(commune__iso_code=uparcel[0], section=uparcel[1], num_parcel=uparcel[2])
            for uparcel in unique_parcels
        ]

        # get parcels with detections but no detections with control status != NOT_CONTROLLED
        parcels = (
            Parcel.objects.annotate(
                nbr_detections=Count("detection_objects__detections"),
            )
            .filter(
                reduce(or_, wheres),
                ~Q(
                    detection_objects__detections__detection_data__detection_control_status__in=[
                        DetectionControlStatus.CONTROLLED_FIELD,
                        DetectionControlStatus.PRIOR_LETTER_SENT,
                        DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
                        DetectionControlStatus.OBSERVARTION_REPORT_REDACTED,
                        DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
                        DetectionControlStatus.REHABILITATED,
                    ]
                ),
                ~Q(
                    detection_objects__detections__detection_data__detection_validation_status=DetectionValidationStatus.INVALIDATED
                ),
                nbr_detections__gt=0,
            )
            .prefetch_related(
                Prefetch(
                    "detection_objects",
                    queryset=DetectionObject.objects.prefetch_related(
                        Prefetch(
                            "detections",
                            queryset=Detection.objects.select_related("detection_data")
                            .prefetch_related(
                                "detection_data__detection_authorizations"
                            )
                            .defer("geometry"),
                        )
                    ),
                )
            )
            .select_related("commune")
        )

        return parcels.all()

    @staticmethod
    def reconcile_parcels(
        data: List[DataOutputRow], parcels: List[Parcel]
    ) -> List[DataOutputRow]:
        # Create a lookup dictionary for fast parcel matching
        # Key: (commune_iso_code, section, num_parcel)
        parcel_lookup = {
            (parcel.commune.iso_code, parcel.section, parcel.num_parcel): parcel
            for parcel in parcels
        }

        # Populate each data item's parcels field
        for item in data:
            commune_code = item.data_input["COMM"]
            matched_parcels = []

            for data_parcel in item.data_parcels:
                key = (commune_code, data_parcel.section, data_parcel.num)
                parcel = parcel_lookup.get(key)

                if parcel:
                    matched_parcels.append(parcel)

            item.parcels = matched_parcels if matched_parcels else None

        return data

    def update_database(self, data: List[DataOutputRow], persist_data: bool):
        detection_datas_to_update_map = defaultdict(
            int
        )  # structure: { detection_data_id: detection_data }
        detection_authorization_to_insert = []

        for item in data:
            if not item.parcels:
                continue

            for parcel in item.parcels:
                self.dpt_parcels_ids_updated_map[item.data_input["DEP_CODE"]].add(
                    parcel.id
                )

                for detection_object in parcel.detection_objects.all():
                    self.dpt_detection_objects_ids_updated_map[
                        item.data_input["DEP_CODE"]
                    ].add(detection_object.id)

                    for detection in detection_object.detections.all():
                        detection_data = (
                            detection_datas_to_update_map.get(
                                detection.detection_data.id
                            )
                            or detection.detection_data
                        )

                        # if authorization already exists, we skip
                        if any(
                            auth.authorization_id == item.data_input["NUM_DAU"]
                            for auth in detection_data.detection_authorizations.all()
                        ):
                            continue

                        detection_data.detection_validation_status = (
                            DetectionValidationStatus.LEGITIMATE
                        )
                        detection_data.detection_validation_status_change_reason = (
                            DetectionValidationStatusChangeReason.SITADEL
                        )

                        detection_authorization_to_insert.append(
                            DetectionAuthorization(
                                authorization_date=item.data_input[
                                    "DATE_REELLE_AUTORISATION"
                                ],
                                authorization_id=item.data_input["NUM_DAU"],
                                detection_data=detection_data,
                            )
                        )

                        detection_datas_to_update_map[detection_data.id] = (
                            detection_data
                        )

        if not persist_data:
            return

        DetectionData.objects.bulk_update(
            objs=detection_datas_to_update_map.values(),
            fields=[
                "detection_validation_status",
                "detection_validation_status_change_reason",
            ],
            batch_size=BULK_UPDATE_BATCH_SIZE,
        )
        DetectionAuthorization.objects.bulk_create(
            objs=detection_authorization_to_insert
        )

    def log(self):
        departments = list(
            set(
                list(self.dpt_detection_objects_ids_updated_map.keys())
                + list(self.dpt_parcels_ids_updated_map.keys())
            )
        )
        log_event(
            f"""DATA UPDATED: {sum(len(ids) for ids in self.dpt_detection_objects_ids_updated_map.values())} detection objects, {sum(len(ids) for ids in self.dpt_parcels_ids_updated_map.values())} parcels
{'\n'.join([f'- {dpt}: {len(self.dpt_detection_objects_ids_updated_map.get(dpt, set()))} detection objects, {len(self.dpt_parcels_ids_updated_map.get(dpt, set()))} parcels' for dpt in departments])}
"""
        )


# utils


def get_num_parcel(num_cadastre: str) -> Optional[int]:
    filtered_num = "".join([i for i in num_cadastre if i.isdigit()])
    return int(filtered_num) if filtered_num else None


def get_data_output(data_input: DataInputRow) -> DataOutputRow:
    data_parcels = []

    for num_cadastre in ["1", "2", "3"]:
        section_cadastre_input = data_input[f"SEC_CADASTRE{num_cadastre}"]
        num_cadastre_input = data_input[f"NUM_CADASTRE{num_cadastre}"]

        if not section_cadastre_input or not num_cadastre_input:
            continue

        num_parcel = get_num_parcel(num_cadastre_input)

        if num_parcel is None:
            continue

        data_parcels.append(DataParcel(section=section_cadastre_input, num=num_parcel))

    return DataOutputRow(
        data_parcels=data_parcels,
        data_input={
            key: value
            for key, value in data_input.items()
            if key in DataInputWithoutParcels.__annotations__.keys()
        },
    )
