from collections import defaultdict
import csv
import tempfile
import time
from dataclasses import dataclass
from functools import reduce
from typing import List, Literal, Optional, Set, Tuple, TypedDict
from django.core.management.base import BaseCommand, CommandError
from core.management.base import CommandRunTrackerMixin
from core.management.commands._common.file import download_file, download_json
from django.db import transaction

from core.constants.detection import CONTROLLED_DETECTION_STATUSES
from core.models.detection_authorization import DetectionAuthorization
from core.models.detection_data import (
    DetectionData,
    DetectionValidationStatus,
    DetectionValidationStatusChangeReason,
)
from core.models.parcel import Parcel
from core.utils.logs_helpers import log_command_event, log_command_progress
from core.utils.cache import invalidate_count_caches
from operator import or_
from django.db.models import Q, Count, Prefetch
from core.models.detection_object import DetectionObject
from core.models.detection import Detection

BATCH_SIZE = 100
BULK_UPDATE_BATCH_SIZE = 1000

# SDES "DiDo" open-data platform. SITADEL_DATASET_ID is the "Liste des permis de
# construire et autres autorisations d'urbanisme" dataset (created 2023-09,
# refreshed monthly). If it ever changes, override with --dataset-id — find the
# new id in the catalogue link on:
# https://www.statistiques.developpement-durable.gouv.fr/donnees-des-permis-de-construire-et-autres-autorisations-durbanisme
DIDO_API_BASE = "https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1"
SITADEL_DATASET_ID = "6513f0189d7d312c80ec5b5b"


def log_event(info: str):
    log_command_event(command_name="import_sitadel", info=info)


def _select_autorisations_datafiles(dataset: dict) -> List[Tuple[str, str, str]]:
    """(title, rid, latest_millesime) for each "autorisations d'urbanisme créant
    des …" datafile (logements / locaux non résidentiels), matched by title so
    the permis d'aménager / démolir datafiles of the same dataset are left out."""
    selected = []
    for datafile in dataset.get("datafiles", []):
        if "autorisation" not in datafile["title"].lower():
            continue
        millesimes = datafile.get("millesimes") or []
        if not millesimes:
            continue
        latest = max(millesimes, key=lambda m: m["millesime"])
        selected.append((datafile["title"], datafile["rid"], latest["millesime"]))
    return selected


def download_latest_autorisations_csvs(
    dataset_id: str = SITADEL_DATASET_ID,
) -> List[Tuple[str, "tempfile.TemporaryDirectory[str]", str]]:
    """Download the latest millesime of both autorisations CSVs (logements +
    locaux non résidentiels) from the DiDo Sitadel dataset. Returns
    (label, temp_dir, file_path) per file; caller cleans up temp_dir."""
    dataset = download_json(f"{DIDO_API_BASE}/datasets/{dataset_id}")
    log_event(f"Dataset: {dataset['title']} (updated {dataset.get('last_update')})")

    datafiles = _select_autorisations_datafiles(dataset)
    if not datafiles:
        raise CommandError(
            "import_sitadel: no 'autorisations' datafile found in Sitadel dataset"
        )

    downloads = []
    for title, rid, millesime in datafiles:
        url = f"{DIDO_API_BASE}/datafiles/{rid}/csv?millesime={millesime}"
        temp_dir, file_path = download_file(url=url, file_name=f"{rid}.{millesime}.csv")
        downloads.append((f"{title} ({millesime})", temp_dir, file_path))
    return downloads


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


class Command(CommandRunTrackerMixin, BaseCommand):
    help = "Import Sitadel file"
    dpt_detection_objects_ids_updated_map = defaultdict(set)
    dpt_parcels_ids_updated_map = defaultdict(set)

    def add_arguments(self, parser):
        parser.add_argument(
            "--file-csv-path",
            type=str,
            required=False,
            help="CSV to import. If omitted, the latest autorisations CSVs "
            "(logements + locaux non résidentiels) are downloaded from DiDo.",
        )
        parser.add_argument(
            "--dataset-id",
            type=str,
            default=SITADEL_DATASET_ID,
            help="DiDo dataset id to download autorisations CSVs from when "
            "--file-csv-path is omitted. Defaults to the Sitadel dataset; find a "
            "new id in the catalogue link on "
            "https://www.statistiques.developpement-durable.gouv.fr/donnees-des-permis-de-construire-et-autres-autorisations-durbanisme",
        )
        parser.add_argument("--persist-data", type=bool, default=False)
        parser.add_argument("--filter-coms", action="append", required=False)
        parser.add_argument("--filter-dpts", action="append", required=False)

    def handle(self, *args, **options):
        file_csv_path = options["file_csv_path"]
        dataset_id = options["dataset_id"]
        persist_data = options["persist_data"]
        filter_coms = options["filter_coms"]
        filter_dpts = options["filter_dpts"]

        if file_csv_path:
            self.process_file(file_csv_path, persist_data, filter_coms, filter_dpts)
            return

        log_event(
            "No --file-csv-path provided: downloading latest autorisations CSVs from DiDo"
        )
        for label, temp_dir, file_path in download_latest_autorisations_csvs(
            dataset_id
        ):
            log_event(f"Processing {label}")
            try:
                self.process_file(file_path, persist_data, filter_coms, filter_dpts)
            finally:
                temp_dir.cleanup()

    def process_file(
        self,
        file_csv_path: str,
        persist_data: bool,
        filter_coms: Optional[List[str]],
        filter_dpts: Optional[List[str]],
    ):
        file_csv = open(file_csv_path, mode="r", encoding="utf-8")
        file_csv_reader = csv.DictReader(file_csv, delimiter=";")
        # Sitadel exports now prepend a human-readable label row before the
        # technical column-code row (REG_CODE;DEP_CODE;COMM;...). DictReader read
        # the labels — advance to the codes row. Older single-header files already
        # expose COMM as a fieldname here.
        header_rows = 1
        if file_csv_reader.fieldnames and "COMM" not in file_csv_reader.fieldnames:
            file_csv_reader = csv.DictReader(file_csv, delimiter=";")
            header_rows = 2

        if not file_csv_reader.fieldnames or "COMM" not in file_csv_reader.fieldnames:
            raise CommandError(
                "import_sitadel: no technical header row found (missing COMM column)"
            )

        # Cheap extra pass (no CSV parsing) to know the denominator for progress.
        with open(file_csv_path, mode="r", encoding="utf-8") as f:
            total = max(sum(1 for _ in f) - header_rows, 0)

        start_time = time.monotonic()
        while True:
            csv_data = self.extract_data_from_csv(
                file_csv_reader=file_csv_reader,
                filter_coms=filter_coms,
                filter_dpts=filter_dpts,
            )

            if not csv_data:
                break

            parcels = self.get_parcels(csv_data)

            csv_data = self.reconcile_parcels(csv_data, parcels)
            self.update_database(data=csv_data, persist_data=persist_data)

            self.log()
            log_command_progress(
                "import_sitadel",
                min(file_csv_reader.line_num - 1, total),
                total,
                start_time,
            )

    @staticmethod
    def extract_data_from_csv(
        file_csv_reader: csv.DictReader,
        filter_coms: Optional[List[str]],
        filter_dpts: Optional[List[str]],
    ) -> List[DataOutputRow]:
        data = []

        for row in file_csv_reader:
            # état = Annulé
            if row["ETAT_DAU"] == "4":
                continue

            # Filter on the DEP_CODE column, not COMM[:2]: overseas departments
            # have 3-digit codes (Réunion 974, commune 97411), so COMM[:2] would
            # wrongly read "97" and drop every overseas row.
            if filter_dpts and row["DEP_CODE"] not in filter_dpts:
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
        # dedup parcels to keep the SQL OR-filter small. structure: Set[(commune, section, num)]
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

        # Only keep parcels whose detections were never acted on by a user:
        # parcels that have detections but none with a control status other than
        # NOT_CONTROLLED. This guards against the Sitadel import overwriting a
        # user's manual control decision (update_database below touches every
        # detection of a returned parcel, so a single controlled detection must
        # exclude the whole parcel).
        #
        # .exclude() compiles to a NOT EXISTS subquery: keep the parcel iff none
        # of its detections is controlled. CONTROLLED_DETECTION_STATUSES is
        # derived from the enum, so a newly added status can't silently slip past
        # this guard.
        parcels = (
            Parcel.objects.annotate(
                nbr_detections=Count("detection_objects__detections"),
            )
            .filter(
                reduce(or_, wheres),
                nbr_detections__gt=0,
            )
            .exclude(
                detection_objects__detections__detection_data__detection_control_status__in=CONTROLLED_DETECTION_STATUSES
            )
            .prefetch_related(
                Prefetch(
                    "detection_objects",
                    queryset=DetectionObject.objects.exclude(
                        detections__detection_data__detection_validation_status=DetectionValidationStatus.INVALIDATED
                    ).prefetch_related(
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
        parcel_lookup = {
            (parcel.commune.iso_code, parcel.section, parcel.num_parcel): parcel
            for parcel in parcels
        }

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
        # bulk_update / bulk_create bypass post_save; invalidate counts explicitly.
        transaction.on_commit(invalidate_count_caches)

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
