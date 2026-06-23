import csv
from datetime import datetime
from typing import List, Optional, Tuple

from django.core.management.base import BaseCommand
from core.management.base import CommandRunTrackerMixin
from django.db import transaction
from django.db.models import Prefetch

from core.models.detection import Detection
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
)
from core.models.detection_object import DetectionObject
from core.models.parcel import Parcel
from core.utils.logs_helpers import log_command_event

COMMAND_NAME = "import_control_statuses"

COL_INSEE = "COM_INSEE"
COL_SECTION = "PARCELLE_SECTION"
COL_NUM = "PARCELLE_NUM"
COL_STATUS_1 = "STATUT_CONTROLE_1"
COL_STATUS_2 = "STATUT_CONTROLE_2"
REQUIRED_COLUMNS = {COL_INSEE, COL_SECTION, COL_NUM, COL_STATUS_1, COL_STATUS_2}

# CSV status label -> DetectionControlStatus. Keys are normalized (stripped + lowercased)
# so matching is case/whitespace-insensitive (the CSV mixes "Jugement"/"jugement", and
# "Astreinte Administratives" with a trailing "s").
CONTROL_STATUS_MAP = {
    "pv dressé": DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
    "jugement": DetectionControlStatus.JUGEMENT,
    "astreinte administrative": DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
    "astreinte administratives": DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
    "remis en état": DetectionControlStatus.REHABILITATED,
    "rapport de constatation redigé": DetectionControlStatus.OBSERVARTION_REPORT_REDACTED,
    "contrôlé terrain": DetectionControlStatus.CONTROLLED_FIELD,
}

# "Prescrit" is a *prescription* state, not a control state. It cannot be expressed as a
# DetectionControlStatus, so it is applied to detection_prescription_status instead and
# leaves detection_control_status untouched.
PRESCRIPTION_STATUS_MAP = {
    "prescrit": DetectionPrescriptionStatus.PRESCRIBED,
}


def log_event(info: str):
    log_command_event(command_name=COMMAND_NAME, info=info)


def normalize_label(label: str) -> str:
    return label.strip().lower()


def normalize_section(raw_section: str) -> str:
    """Match the cadastre storage format.

    Sections are stored on 2 chars: single-letter sections are left zero-padded
    ("B" -> "0B", "A" -> "0A"), two-letter sections ("ZH", "AC") are kept as-is.
    The CSV uses the unpadded form and sometimes has trailing spaces ("A ").
    """
    section = raw_section.strip().upper()
    if len(section) == 1:
        section = section.rjust(2, "0")
    return section


def resolve_status(label: str) -> Tuple[Optional[str], Optional[str], bool]:
    """Resolve a raw CSV status label.

    Returns (control_status, prescription_status, known). At most one of the two
    statuses is set. `known` is False when the label is non-empty but maps to nothing,
    so the caller can skip the row and report it instead of guessing.
    """
    normalized = normalize_label(label)
    if not normalized:
        return None, None, True

    control_status = CONTROL_STATUS_MAP.get(normalized)
    if control_status is not None:
        return control_status, None, True

    prescription_status = PRESCRIPTION_STATUS_MAP.get(normalized)
    if prescription_status is not None:
        return None, prescription_status, True

    return None, None, False


def build_parcel_queryset(insee: str, section: str, num_parcel: int):
    # only consider live detections/detection objects: DeletableModelMixin does NOT
    # filter soft-deleted rows at the manager level, so it must be done explicitly.
    return Parcel.objects.filter(
        commune__iso_code=insee,
        section=section,
        num_parcel=num_parcel,
    ).prefetch_related(
        Prefetch(
            "detection_objects",
            queryset=DetectionObject.objects.filter(deleted=False).prefetch_related(
                Prefetch(
                    "detections",
                    queryset=Detection.objects.filter(deleted=False).select_related(
                        "detection_data"
                    ),
                )
            ),
        )
    )


class Command(CommandRunTrackerMixin, BaseCommand):
    help = (
        "Update detection control / prescription statuses from a per-parcel CSV "
        f"(columns: {COL_INSEE}, {COL_SECTION}, {COL_NUM}, {COL_STATUS_1}, "
        f"{COL_STATUS_2}). When both status columns are filled, {COL_STATUS_2} wins."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv-path", type=str, required=True, help="Path to the CSV file to import"
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Analyse and log what would change without writing anything",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        dry_run = options["dry_run"]

        log_event(
            f"IMPORT CONTROL STATUSES: starting (csv_path={csv_path}, dry_run={dry_run})"
        )

        with open(csv_path, mode="r") as csv_file:
            rows = list(csv.DictReader(csv_file, delimiter=","))

        if not rows:
            log_event("IMPORT CONTROL STATUSES: ABORT, empty CSV")
            return

        missing_columns = REQUIRED_COLUMNS - set(rows[0].keys())
        if missing_columns:
            log_event(
                f"IMPORT CONTROL STATUSES: ABORT, missing columns: {sorted(missing_columns)}"
            )
            return

        counters = {
            "rows_total": len(rows),
            "rows_no_status": 0,
            "rows_invalid_num": 0,
            "rows_unknown_status": 0,
            "parcels_found": 0,
            "parcels_not_found": 0,
            "detection_objects_updated": 0,
            "detections_updated": 0,
        }
        applied_by_status: dict[str, int] = {}
        parcels_not_found: List[list] = []
        unknown_statuses: List[list] = []

        with transaction.atomic():
            # +1 for the header line, +1 because enumerate is 0-based -> human line numbers
            for line_number, row in enumerate(rows, start=2):
                insee = (row.get(COL_INSEE) or "").strip()
                raw_section = row.get(COL_SECTION) or ""
                raw_num = (row.get(COL_NUM) or "").strip()

                status_1 = (row.get(COL_STATUS_1) or "").strip()
                status_2 = (row.get(COL_STATUS_2) or "").strip()
                # conflict rule: STATUT_CONTROLE_2 wins when present
                effective_label = status_2 if status_2 else status_1

                if not effective_label:
                    counters["rows_no_status"] += 1
                    log_event(
                        f"IMPORT CONTROL STATUSES: line {line_number}: no status, skipping "
                        f"({insee} {raw_section.strip()} {raw_num})"
                    )
                    continue

                try:
                    num_parcel = int(raw_num)
                except (TypeError, ValueError):
                    counters["rows_invalid_num"] += 1
                    log_event(
                        f"IMPORT CONTROL STATUSES: line {line_number}: invalid "
                        f"{COL_NUM}={raw_num!r}, skipping"
                    )
                    continue

                control_status, prescription_status, known = resolve_status(
                    effective_label
                )
                if not known:
                    counters["rows_unknown_status"] += 1
                    unknown_statuses.append(
                        [insee, raw_section.strip(), raw_num, effective_label]
                    )
                    log_event(
                        f"IMPORT CONTROL STATUSES: line {line_number}: unknown status "
                        f"{effective_label!r}, skipping (no data written)"
                    )
                    continue

                section = normalize_section(raw_section)
                parcels = list(build_parcel_queryset(insee, section, num_parcel))

                if not parcels:
                    counters["parcels_not_found"] += 1
                    parcels_not_found.append(
                        [insee, raw_section.strip(), raw_num, section, effective_label]
                    )
                    log_event(
                        f"IMPORT CONTROL STATUSES: line {line_number}: parcel not found "
                        f"(insee={insee}, section={section}, num={num_parcel})"
                    )
                    continue

                counters["parcels_found"] += 1
                if len(parcels) > 1:
                    log_event(
                        f"IMPORT CONTROL STATUSES: line {line_number}: {len(parcels)} "
                        f"parcels match (insee={insee}, section={section}, "
                        f"num={num_parcel}); updating all"
                    )

                for parcel in parcels:
                    for detection_object in parcel.detection_objects.all():
                        object_touched = False
                        for detection in detection_object.detections.all():
                            detection_data = detection.detection_data
                            if detection_data is None:
                                continue

                            if control_status is not None:
                                # set_detection_control_status applies the business rules:
                                # un-prescribes on OFFICIAL_REPORT_DRAWN_UP and upgrades
                                # DETECTED_NOT_VERIFIED -> SUSPECT.
                                detection_data.set_detection_control_status(
                                    control_status
                                )
                            if prescription_status is not None:
                                detection_data.detection_prescription_status = (
                                    prescription_status
                                )

                            if not dry_run:
                                detection_data.save()
                            counters["detections_updated"] += 1
                            object_touched = True

                        if object_touched:
                            counters["detection_objects_updated"] += 1

                applied_by_status[effective_label] = (
                    applied_by_status.get(effective_label, 0) + 1
                )

            if dry_run:
                log_event(
                    "IMPORT CONTROL STATUSES: DRY-RUN, rolling back (no data written)"
                )
                transaction.set_rollback(True)

        self._write_reports(parcels_not_found, unknown_statuses)
        self._log_summary(counters, applied_by_status, dry_run)

    @staticmethod
    def _write_reports(parcels_not_found: List[list], unknown_statuses: List[list]):
        suffix = datetime.today().strftime("%Y-%m-%d-%H%M%S")

        if parcels_not_found:
            filename = f"import_control_statuses_parcels_not_found-{suffix}.csv"
            with open(filename, "w", newline="") as report_file:
                writer = csv.writer(report_file)
                writer.writerow(
                    [
                        COL_INSEE,
                        COL_SECTION,
                        COL_NUM,
                        "SECTION_NORMALIZED",
                        "EFFECTIVE_STATUS",
                    ]
                )
                writer.writerows(parcels_not_found)
            log_event(
                f"IMPORT CONTROL STATUSES: parcels not found saved here={filename}"
            )

        if unknown_statuses:
            filename = f"import_control_statuses_unknown_statuses-{suffix}.csv"
            with open(filename, "w", newline="") as report_file:
                writer = csv.writer(report_file)
                writer.writerow([COL_INSEE, COL_SECTION, COL_NUM, "EFFECTIVE_STATUS"])
                writer.writerows(unknown_statuses)
            log_event(
                f"IMPORT CONTROL STATUSES: unknown statuses saved here={filename}"
            )

    @staticmethod
    def _log_summary(counters: dict, applied_by_status: dict, dry_run: bool):
        log_event(
            "IMPORT CONTROL STATUSES: FINISHED" + (" (DRY-RUN)" if dry_run else "")
        )
        log_event(f"IMPORT CONTROL STATUSES: rows total={counters['rows_total']}")
        log_event(
            f"IMPORT CONTROL STATUSES: rows without status={counters['rows_no_status']}"
        )
        log_event(
            f"IMPORT CONTROL STATUSES: rows invalid num={counters['rows_invalid_num']}"
        )
        log_event(
            f"IMPORT CONTROL STATUSES: rows unknown status={counters['rows_unknown_status']}"
        )
        log_event(f"IMPORT CONTROL STATUSES: parcels found={counters['parcels_found']}")
        log_event(
            f"IMPORT CONTROL STATUSES: parcels not found={counters['parcels_not_found']}"
        )
        log_event(
            f"IMPORT CONTROL STATUSES: detection objects updated={counters['detection_objects_updated']}"
        )
        log_event(
            f"IMPORT CONTROL STATUSES: detections updated={counters['detections_updated']}"
        )
        for status_label, count in sorted(applied_by_status.items()):
            log_event(
                f"IMPORT CONTROL STATUSES: applied '{status_label}' on {count} matched row(s)"
            )
