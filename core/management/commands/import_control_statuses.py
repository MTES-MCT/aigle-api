"""Update detection control statuses from a per-parcel CSV.

The CSV holds one control status per row, in a single STATUT_CONTROLE column: a row
names a parcel (INSEE code + cadastral section + number) and the status to apply to
every live detection sitting on it.

Template to hand out to the services filling it: docs/import_control_statuses_template.csv
"""

import csv
import re
import time
import unicodedata
from datetime import UTC, date, datetime, time as time_of_day
from typing import Dict, List, NamedTuple, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Prefetch

from core.management.base import CommandRunTrackerMixin
from core.models.detection import Detection
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionPrescriptionStatus,
)
from core.models.detection_object import DetectionObject
from core.models.parcel import Parcel
from core.models.user import User
from core.utils.cache import invalidate_count_caches, suppress_count_cache_invalidation
from core.utils.logs_helpers import log_command_event, log_command_progress

COMMAND_NAME = "import_control_statuses"

COL_INSEE = "COM_INSEE"
COL_SECTION = "PARCELLE_SECTION"
COL_NUM = "PARCELLE_NUM"
COL_STATUS = "STATUT_CONTROLE"
# optional: a row without a date is imported, it just carries no date information
COL_DATE = "DATE"
REQUIRED_COLUMNS = (COL_INSEE, COL_SECTION, COL_NUM, COL_STATUS)

DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d")

PROGRESS_LOG_EVERY = 100

# Characters that survive NFKD and would break an otherwise exact match: zero-width
# spaces, soft hyphen, direction marks, a BOM pasted in the middle of a cell.
_INVISIBLE_RE = re.compile(r"[\u00ad\u200b-\u200f\u2060\ufeff]")
# Word separators. NFKD has already rewritten non-breaking and thin spaces as plain ones.
_SEPARATORS_RE = re.compile(r"[\s\-_]+")
# Punctuation an external file may wrap a label in: "PV dressé.", « Remis en état »
_SURROUNDING_PUNCTUATION = " .,;:!?*\"'`«»()[]{}"


def _singular(word: str) -> str:
    """Fold the plural mark of a word ("astreintes" -> "astreinte").

    Both the map keys and the CSV labels go through it and no two statuses differ only
    by a plural, so this can only ever turn a near miss into a match.
    """
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def normalize_label(label: str) -> str:
    """Case-, accent-, spacing- and plural-insensitive form used to look a label up.

    The maps are built with it too, so both sides of the lookup are compared on the same
    form: whatever spelling the external file uses ("REMIS  EN  ETAT", "Astreintes
    administratives.", a value pasted from Word with a non-breaking or zero-width space
    in it) reaches the same key.
    """
    # NFKD splits an accented letter into letter + combining mark (dropped right after)
    # and rewrites non-breaking / thin spaces as plain ones.
    decomposed = unicodedata.normalize("NFKD", label)
    visible = _INVISIBLE_RE.sub(
        "", "".join(char for char in decomposed if not unicodedata.combining(char))
    )
    words = _SEPARATORS_RE.sub(" ", visible).strip(_SURROUNDING_PUNCTUATION).split()
    return " ".join(_singular(word.casefold()) for word in words)


def _build_label_map(labels: dict, statuses) -> dict:
    """Normalized label -> status, every enum value included so a CSV exported from the
    app imports back as-is.

    Raises when two labels normalize to the same key for different statuses: the maps are
    static, so a collision is a coding mistake to catch at import time rather than a row
    to silently mis-assign.
    """
    mapping = {}

    for label, status in [
        *((status.value, status) for status in statuses),
        *labels.items(),
    ]:
        key = normalize_label(label)
        colliding = mapping.get(key)
        if colliding is not None and colliding != status:
            raise ValueError(
                f"label {label!r} normalizes to {key!r}, already mapped to {colliding}"
            )
        mapping[key] = status

    return mapping


# One entry per control status the app displays (mirrors the frontend
# DETECTION_CONTROL_STATUSES_NAMES_MAP), plus the wordings met in the DDTM files. Case,
# accents, hyphens, plurals, repeated spaces and surrounding punctuation are handled by
# normalize_label and need no entry of their own.
_CONTROL_STATUS_LABELS = {
    "Non contrôlé": DetectionControlStatus.NOT_CONTROLLED,
    "À contrôler": DetectionControlStatus.TO_CONTROL,
    "Courrier préalable envoyé": DetectionControlStatus.PRIOR_LETTER_SENT,
    "Contrôlé terrain": DetectionControlStatus.CONTROLLED_FIELD,
    "PV dressé": DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
    "Procès-verbal dressé": DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
    "Rapport de constatations rédigé": DetectionControlStatus.OBSERVARTION_REPORT_REDACTED,
    "Astreinte administrative": DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
    "En jugement": DetectionControlStatus.JUGEMENT,
    "Jugement": DetectionControlStatus.JUGEMENT,
    "Remis en état": DetectionControlStatus.REHABILITATED,
}

CONTROL_STATUS_MAP: Dict[str, DetectionControlStatus] = _build_label_map(
    _CONTROL_STATUS_LABELS, DetectionControlStatus
)

# "Prescrit" / "Non prescrit" describe prescription, not control: they have no
# DetectionControlStatus equivalent, so they are written to detection_prescription_status
# and leave detection_control_status untouched.
_PRESCRIPTION_STATUS_LABELS = {
    "Prescrit": DetectionPrescriptionStatus.PRESCRIBED,
    "Non prescrit": DetectionPrescriptionStatus.NOT_PRESCRIBED,
}

PRESCRIPTION_STATUS_MAP: Dict[str, DetectionPrescriptionStatus] = _build_label_map(
    _PRESCRIPTION_STATUS_LABELS, DetectionPrescriptionStatus
)

# Counters, in the order they are logged at the end of the run.
COUNTER_LABELS = {
    "rows_total": "rows total",
    "rows_no_status": "rows without status",
    "rows_invalid_num": f"rows with an invalid {COL_NUM}",
    "rows_invalid_date": f"rows with an invalid {COL_DATE}",
    "rows_unknown_status": "rows with an unknown status",
    "rows_overriding": "rows overriding an earlier row for the same parcel",
    "parcels_targeted": "parcels targeted",
    "parcels_found": "parcels found",
    "parcels_not_found": "parcels not found",
    "detection_objects_updated": "detection objects updated",
    "detections_updated": "detections updated",
}


class ResolvedStatus(NamedTuple):
    control: Optional[DetectionControlStatus]
    prescription: Optional[DetectionPrescriptionStatus]

    @property
    def name(self) -> str:
        return (self.control or self.prescription).value


class ParcelKey(NamedTuple):
    insee: str
    section: str
    num_parcel: int


class ParcelTarget(NamedTuple):
    status: ResolvedStatus
    label: str
    line_number: int
    raw_section: str
    raw_num: str
    date: Optional[date]


def log_event(info: str):
    log_command_event(command_name=COMMAND_NAME, info=info)


def normalize_section(raw_section: str) -> str:
    """Match the cadastre storage format.

    Sections are stored on 2 chars: single-letter sections are left zero-padded
    ("B" -> "0B"), two-letter sections ("ZH", "AC") are kept as-is. The CSV uses the
    unpadded form and sometimes has trailing spaces ("A ").
    """
    section = raw_section.strip().upper()
    if len(section) == 1:
        section = section.rjust(2, "0")
    return section


def parse_date(raw_date: str) -> Optional[date]:
    """Parse a CSV date, None when it matches none of DATE_FORMATS.

    Only the first token is read: Excel writes a date-only cell back with a trailing
    time often enough ("12/03/2025 00:00") to be worth ignoring.
    """
    value = raw_date.strip().split(" ")[0]

    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    return None


def to_datetime(value: date) -> datetime:
    """Midday UTC of that date.

    updated_at is a timestamp rendered in the reader's own timezone, and the app serves
    territories from UTC-4 (Martinique) to UTC+4 (Réunion): anchoring at midday keeps the
    displayed day equal to the day written in the CSV for all of them, where midnight
    would show the day before or after.
    """
    return datetime.combine(value, time_of_day(hour=12), tzinfo=UTC)


def resolve_status(normalized_label: str) -> Optional[ResolvedStatus]:
    """Resolve a label already run through normalize_label, None when it maps to nothing.

    At most one of the two statuses is set; a None result makes the caller report the
    row rather than guess.
    """
    control_status = CONTROL_STATUS_MAP.get(normalized_label)
    if control_status is not None:
        return ResolvedStatus(control=control_status, prescription=None)

    prescription_status = PRESCRIPTION_STATUS_MAP.get(normalized_label)
    if prescription_status is not None:
        return ResolvedStatus(control=None, prescription=prescription_status)

    return None


def read_csv_rows(csv_path: str) -> List[dict]:
    # utf-8-sig: Excel exports carry a BOM, which would otherwise stick to the first
    # column name and fail the required-column check.
    with open(csv_path, mode="r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=",")
        # Reading .fieldnames consumes the header line; assigning it back replaces the
        # keys of every row to come, so surrounding spaces never hide a column.
        fieldnames = [(name or "").strip() for name in reader.fieldnames or []]
        reader.fieldnames = fieldnames

        missing_columns = sorted(set(REQUIRED_COLUMNS) - set(fieldnames))
        if missing_columns:
            raise CommandError(
                f"missing columns: {missing_columns} (found: {fieldnames})"
            )

        rows = list(reader)

    if not rows:
        raise CommandError(f"empty CSV: {csv_path}")

    return rows


def resolve_user(user_email: str) -> User:
    """The user recorded as the author of every row the import changes."""
    user = User.objects.filter(email__iexact=user_email.strip(), deleted=False).first()

    if user is None:
        raise CommandError(f"user not found: {user_email!r}")

    return user


def build_parcel_queryset(key: ParcelKey):
    # DeletableModelMixin does not filter soft-deleted rows at the manager level, so
    # every level of the walk has to exclude them explicitly.
    return Parcel.objects.filter(
        deleted=False,
        commune__iso_code=key.insee,
        section=key.section,
        num_parcel=key.num_parcel,
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
        f"(columns: {', '.join(REQUIRED_COLUMNS)}, plus an optional {COL_DATE}). The "
        "status of a row is applied to every live detection of every live detection "
        f"object of the matching parcel. {COL_DATE} sets the update date, and the "
        "official report date when the status draws a PV up. When a parcel appears on "
        "several rows, the last one wins."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv-path", type=str, required=True, help="Path to the CSV file to import"
        )
        parser.add_argument(
            "--user-email",
            type=str,
            required=True,
            help="Email of the user recorded as the author of the updates",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Analyse and log what would change without writing anything",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        dry_run = options["dry_run"]
        self.user = resolve_user(options["user_email"])

        log_event(
            f"Starting importing control statuses... (user={self.user.email}, dry_run={dry_run})"
        )

        self.counters = dict.fromkeys(COUNTER_LABELS, 0)
        self.applied_by_status: Dict[str, int] = {}
        self.parcels_not_found: List[list] = []
        self.unknown_statuses: List[list] = []

        rows = read_csv_rows(csv_path)
        self.counters["rows_total"] = len(rows)

        targets = self.collect_targets(rows)
        self.counters["parcels_targeted"] = len(targets)

        self.apply_targets(targets, dry_run=dry_run)

        self.write_reports()
        self.log_summary(dry_run=dry_run)

    def collect_targets(self, rows: List[dict]) -> Dict[ParcelKey, ParcelTarget]:
        """Turn the rows into one target per parcel, dropping the ones that can't be used.

        A parcel repeated on several rows is kept once: the last row wins (the previous
        two-column "STATUT_CONTROLE_2 overrides STATUT_CONTROLE_1" rule, applied to rows).
        """
        targets: Dict[ParcelKey, ParcelTarget] = {}

        # +2: line 1 is the header and enumerate is 0-based -> human line numbers
        for line_number, row in enumerate(rows, start=2):
            insee = (row.get(COL_INSEE) or "").strip()
            raw_section = (row.get(COL_SECTION) or "").strip()
            raw_num = (row.get(COL_NUM) or "").strip()
            raw_date = (row.get(COL_DATE) or "").strip()
            label = (row.get(COL_STATUS) or "").strip()
            # a placeholder cell ("-", "...") normalizes away: no status, not an unknown one
            normalized_label = normalize_label(label)

            if not normalized_label:
                self.counters["rows_no_status"] += 1
                continue

            try:
                num_parcel = int(raw_num)
            except ValueError:
                self.counters["rows_invalid_num"] += 1
                log_event(
                    f"Line {line_number}: invalid {COL_NUM}={raw_num!r}, skipping"
                )
                continue

            row_date = parse_date(raw_date) if raw_date else None
            if raw_date and row_date is None:
                self.counters["rows_invalid_date"] += 1
                log_event(
                    f"Line {line_number}: invalid {COL_DATE}={raw_date!r}, skipping"
                )
                continue

            status = resolve_status(normalized_label)
            if status is None:
                self.counters["rows_unknown_status"] += 1
                self.unknown_statuses.append([insee, raw_section, raw_num, label])
                log_event(
                    f"Line {line_number}: unknown status {label!r}, skipping (no data written)"
                )
                continue

            key = ParcelKey(
                insee=insee,
                section=normalize_section(raw_section),
                num_parcel=num_parcel,
            )
            previous = targets.get(key)
            if previous is not None and previous.status != status:
                self.counters["rows_overriding"] += 1
                log_event(
                    f"Line {line_number}: parcel {insee} {key.section} {num_parcel} already "
                    f"had status {previous.label!r} (line {previous.line_number}), "
                    f"{label!r} wins"
                )

            targets[key] = ParcelTarget(
                status=status,
                label=label,
                line_number=line_number,
                raw_section=raw_section,
                raw_num=raw_num,
                date=row_date,
            )

        return targets

    def apply_targets(self, targets: Dict[ParcelKey, ParcelTarget], dry_run: bool):
        total = len(targets)
        start_time = time.monotonic()

        # A per-row save() bumps the count-cache version once per detection: suppress the
        # signal and invalidate once at the end, as the contextmanager contract requires.
        with suppress_count_cache_invalidation():
            for done, (key, target) in enumerate(targets.items(), start=1):
                self.apply_target(key, target, dry_run=dry_run)

                if done % PROGRESS_LOG_EVERY == 0 or done == total:
                    log_command_progress(COMMAND_NAME, done, total, start_time)

        if not dry_run and self.counters["detections_updated"]:
            invalidate_count_caches()

    def apply_target(self, key: ParcelKey, target: ParcelTarget, dry_run: bool):
        parcels = list(build_parcel_queryset(key))

        if not parcels:
            self.counters["parcels_not_found"] += 1
            self.parcels_not_found.append(
                [
                    key.insee,
                    target.raw_section,
                    target.raw_num,
                    key.section,
                    target.label,
                ]
            )
            log_event(
                f"Line {target.line_number}: parcel not found (insee={key.insee}, "
                f"section={key.section}, num={key.num_parcel})"
            )
            return

        self.counters["parcels_found"] += len(parcels)
        if len(parcels) > 1:
            log_event(
                f"Line {target.line_number}: {len(parcels)} parcels match (insee={key.insee}, "
                f"section={key.section}, num={key.num_parcel}); updating all"
            )

        # One transaction per parcel: a whole-file transaction would hold locks on rows
        # users edit from the interface for the entire run. The import is idempotent, so
        # a partial run is simply resumed by running the command again.
        with transaction.atomic():
            for parcel in parcels:
                for detection_object in parcel.detection_objects.all():
                    updated_detections = 0

                    for detection in detection_object.detections.all():
                        if self.apply_to_detection(detection, target, dry_run=dry_run):
                            updated_detections += 1

                    if updated_detections:
                        self.counters["detection_objects_updated"] += 1
                        self.counters["detections_updated"] += updated_detections
                        self.applied_by_status[target.status.name] = (
                            self.applied_by_status.get(target.status.name, 0)
                            + updated_detections
                        )

    def apply_to_detection(
        self, detection: Detection, target: ParcelTarget, dry_run: bool
    ) -> bool:
        """Apply the row to a detection, returning whether anything changed.

        Unchanged rows are left alone: saving them would add a history entry (and an
        update) saying nothing, and would credit the import user with a non-change.
        """
        detection_data = detection.detection_data
        if detection_data is None:
            return False

        fields = [
            "detection_control_status",
            "detection_validation_status",
            "detection_prescription_status",
            "official_report_date",
        ]
        before = [getattr(detection_data, field) for field in fields]

        status = target.status
        if status.control is not None:
            # applies the business rules: un-prescribes on OFFICIAL_REPORT_DRAWN_UP and
            # upgrades DETECTED_NOT_VERIFIED -> SUSPECT
            detection_data.set_detection_control_status(status.control)
        if status.prescription is not None:
            detection_data.detection_prescription_status = status.prescription
        if (
            target.date is not None
            and status.control == DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP
        ):
            # the date of the row IS the date the report was drawn up
            detection_data.official_report_date = target.date

        if before == [getattr(detection_data, field) for field in fields]:
            return False

        if dry_run:
            return True

        detection_data.user_last_update = self.user
        # updated_at is auto_now: with update_fields it is only written if listed
        detection_data.save(update_fields=fields + ["user_last_update", "updated_at"])

        if target.date is not None:
            # save() always stamps updated_at with "now" (auto_now), so the date of the
            # row has to be forced through an UPDATE of its own.
            DetectionData.objects.filter(pk=detection_data.pk).update(
                updated_at=to_datetime(target.date)
            )

        return True

    def write_reports(self):
        suffix = datetime.today().strftime("%Y-%m-%d-%H%M%S")
        # utf-8-sig: the reports hold accented labels, and are re-opened in Excel

        if self.parcels_not_found:
            filename = f"import_control_statuses_parcels_not_found-{suffix}.csv"
            with open(filename, "w", newline="", encoding="utf-8-sig") as report_file:
                writer = csv.writer(report_file)
                writer.writerow(
                    [
                        COL_INSEE,
                        COL_SECTION,
                        COL_NUM,
                        "SECTION_NORMALIZED",
                        COL_STATUS,
                    ]
                )
                writer.writerows(self.parcels_not_found)
            log_event(f"Parcels not found saved here={filename}")

        if self.unknown_statuses:
            filename = f"import_control_statuses_unknown_statuses-{suffix}.csv"
            with open(filename, "w", newline="", encoding="utf-8-sig") as report_file:
                writer = csv.writer(report_file)
                writer.writerow([COL_INSEE, COL_SECTION, COL_NUM, COL_STATUS])
                writer.writerows(self.unknown_statuses)
            log_event(f"Unknown statuses saved here={filename}")

    def log_summary(self, dry_run: bool):
        log_event(
            "Finished importing control statuses"
            + (" (DRY-RUN, no data written)" if dry_run else "")
        )

        for counter, label in COUNTER_LABELS.items():
            log_event(f"{label}={self.counters[counter]}")

        for status_name, count in sorted(self.applied_by_status.items()):
            log_event(f"Applied {status_name} on {count} detection(s)")
