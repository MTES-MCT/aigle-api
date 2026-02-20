from datetime import datetime, date
import re
from typing import List, Tuple
from functools import reduce
import operator
from django.core.management.base import BaseCommand, CommandError
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
    DetectionValidationStatusChangeReason,
)
from core.models.parcel import Parcel
from core.services.lucca_analytics import (
    LuccaAnalyticsDatabaseConnector,
    OrderBy,
    RowFilter,
)
from core.utils.logs_helpers import log_command_event
from django.db.models import Q
from core.utils.string import normalize


def log_event(info: str):
    log_command_event(command_name="import_from_lucca", info=info)


def parse_date(date_string: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(
            f"Invalid date format: '{date_string}'. Use YYYY-MM-DD format (e.g., 2012-11-25)"
        )


class Command(BaseCommand):
    help = "Import data from Lucca analytics database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-date",
            type=parse_date,
            required=False,
            help="Minimum date for filtering data (format: YYYY-MM-DD, e.g., 2012-11-25)",
        )
        parser.add_argument(
            "--max-date",
            type=parse_date,
            required=False,
            help="Maximum date for filtering data (format: YYYY-MM-DD, e.g., 2024-12-31)",
        )

    def handle(self, *args, **options):
        min_date = options.get("min_date")
        max_date = options.get("max_date")

        connector = LuccaAnalyticsDatabaseConnector()
        connector.test_connection()
        log_event("successfuly connected to database")

        filters = []

        if min_date:
            filters.append(
                RowFilter(
                    field="action_date",
                    value=min_date,
                    operator=">=",
                )
            )
        if max_date:
            filters.append(
                RowFilter(
                    field="action_date",
                    value=max_date,
                    operator="<=",
                )
            )

        history_rows = connector.get_rows(
            table_name="stats_history",
            filters=filters,
            order_bys=[OrderBy(field="action_date"), OrderBy(field="id")],
        )

        nbr_parcels_updated = 0
        nbr_parcels_not_found = 0

        for row in history_rows:
            # get parcel

            try:
                parcels_from_lucca = extract_parcels(parcels_from_lucca=row["parcelle"])
            except ValueError:
                log_event(
                    f'Lucca row parcel has invalid format: {row["parcelle"]}, skipping...'
                )
                continue

            parcels = (
                Parcel.objects.filter(
                    Q(commune__name_normalized=normalize(row["ville"]))
                )
                .filter(
                    reduce(
                        operator.or_,
                        [
                            Q(section=section, num_parcel=num_parcel)
                            for section, num_parcel in parcels_from_lucca
                        ],
                    )
                )
                .prefetch_related(
                    "detection_objects",
                    "detection_objects__detections",
                    "detection_objects__detections__detection_data",
                )
                .all()
            )

            # Check which parcels were not found
            found_parcels = {(p.section, p.num_parcel) for p in parcels}
            requested_parcels = set(parcels_from_lucca)
            not_found = requested_parcels - found_parcels

            if not_found:
                nbr_parcels_not_found += len(not_found)
                log_event(
                    f"Parcels not found: {not_found} (requested: {requested_parcels}, found: {found_parcels})"
                )

            if not parcels:
                log_event("No parcels found, skipping...")
                continue

            nbr_parcels_updated += len(parcels)

            for parcel in parcels:
                for detection_object in parcel.detection_objects.all():
                    detection_control_status = None
                    detection_validation_status = None

                    # statuts non pris en charge:
                    # Création PV reactualisation
                    # Création décisions de justice

                    if row["action_type"] == "Ouverture dossier":
                        detection_validation_status = DetectionValidationStatus.SUSPECT

                    if row["action_type"] == "Création courrier":
                        detection_control_status = (
                            DetectionControlStatus.PRIOR_LETTER_SENT
                        )

                    if row["action_type"] == "Création PV avec natinfs":
                        detection_control_status = (
                            DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP
                        )

                    if (
                        row["action_type"]
                        == "Création rapport de constatation (PV sans natinfs)"
                    ):
                        detection_control_status = (
                            DetectionControlStatus.OBSERVARTION_REPORT_REDACTED
                        )

                    if row["action_type"] == "Clôture dossier avec remise en état":
                        detection_control_status = DetectionControlStatus.REHABILITATED

                    if row["action_type"] in [
                        "Création contrôle avec droit de visite",
                        "Création contrôle sans droit visite",
                    ]:
                        detection_control_status = (
                            DetectionControlStatus.CONTROLLED_FIELD
                        )

                    for detection in detection_object.detections.all():
                        if (
                            not detection_validation_status
                            and not detection_control_status
                        ):
                            continue

                        detection.detection_data.detection_validation_status_change_reason = DetectionValidationStatusChangeReason.IMPORT_FROM_LUCCA

                        if detection_validation_status:
                            detection.detection_data.detection_validation_status = (
                                detection_validation_status
                            )

                        if detection_control_status:
                            detection.detection_data.set_detection_control_status(
                                detection_control_status
                            )

                        detection.detection_data.save()

        log_event(
            f"finished, nbr parcels updated: {nbr_parcels_updated}, nbr not found: {nbr_parcels_not_found}"
        )


# utils

PARCEL_LUCCA_SEPARATOR = ","


def extract_parcels(parcels_from_lucca: str) -> List[Tuple[str, int]]:
    """
    parcelle_from_lucca: format "OF0888,OF0886,OF0486" or "OF0888, OF0886, OF0486"
    """

    if PARCEL_LUCCA_SEPARATOR not in parcels_from_lucca:
        parcels_str = [parcels_from_lucca]
    else:
        parcels_str = list(
            PARCEL_LUCCA_SEPARATOR.split(parcels_from_lucca.replace(" ", ""))
        )

    return [split_leading_letters(parcel_str) for parcel_str in parcels_str]


def split_leading_letters(text: str) -> Tuple[str, int]:
    match = re.match(r"^([a-zA-Z]+)(.*)", text, re.DOTALL)

    if match is None:
        raise ValueError

    return (match.group(1), int(match.group(2)))
