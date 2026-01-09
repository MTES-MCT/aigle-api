from datetime import datetime, date
from django.core.management.base import BaseCommand, CommandError
from core.models.detection_data import DetectionControlStatus, DetectionValidationStatus
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

        # for now, we do not have access to parcel info
        # once we have access, we can continue
        return

        for row in history_rows:
            # get parcel
            parcel = (
                Parcel.objects.filter(
                    Q(commune__name_normalized=normalize(row["ville"]))
                )
                # .filter(
                #     section=cadastre_letters,
                #     num_parcel=cadastre_numbers,
                # )
                .prefetch_related(
                    "detection_objects",
                    "detection_objects__detections",
                    "detection_objects__detections__detection_data",
                )
                .first()
            )

            if not parcel:
                log_event("Parcel not found")
                continue

            for detection_object in parcel.detection_objects.all():
                detection_control_status = None
                detection_validation_status = None

                # statuts non pris en charge:
                # Création PV reactualisation
                # Création décisions de justice

                if row["action_type"] == "Ouverture dossier":
                    detection_validation_status = DetectionValidationStatus.SUSPECT

                if row["action_type"] == "Création courrier":
                    detection_control_status = DetectionControlStatus.PRIOR_LETTER_SENT

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
                    detection_control_status = DetectionControlStatus.CONTROLLED_FIELD

                for detection in detection_object.detections.all():
                    if detection_validation_status:
                        detection.detection_data.detection_validation_status = (
                            detection_validation_status
                        )

                    if detection_control_status:
                        detection.detection_data.set_detection_control_status(
                            detection_control_status
                        )

                    detection.detection_data.save()
