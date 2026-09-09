"""Tests for the `import_control_statuses` management command.

Covers the CSV contract (single STATUT_CONTROLE column, label matching, parcel
lookup) and the write rules: soft-deleted rows are never touched, unchanged rows are
never saved, and a dry run writes nothing.
"""

import csv
import os
import shutil
import tempfile
from datetime import UTC, date, datetime

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from core.management.commands.import_control_statuses import (
    _CONTROL_STATUS_LABELS,
    _PRESCRIPTION_STATUS_LABELS,
    _build_label_map,
    normalize_label,
    resolve_status,
)
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionData,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_tile,
    create_tile_set,
)
from core.tests.fixtures.geo_data import create_montpellier_commune, create_parcel
from core.tests.fixtures.users import create_admin

MONTPELLIER_INSEE = "34172"
COLUMNS = ["COM_INSEE", "PARCELLE_SECTION", "PARCELLE_NUM", "STATUT_CONTROLE"]
COLUMNS_WITH_DATE = COLUMNS + ["DATE"]
USER_EMAIL = "agent@example.com"


class LabelMatchingTests(SimpleTestCase):
    """The CSV comes from an external service: whatever spelling it uses must land on
    the right status, and anything it does NOT recognise must stay unrecognised."""

    def assert_resolves_to_control(self, label, expected_status):
        status = resolve_status(normalize_label(label))
        self.assertIsNotNone(status, label)
        self.assertEqual(status.control, expected_status, label)

    def test_every_status_is_reachable_by_its_label_and_by_its_enum_value(self):
        for status in DetectionControlStatus:
            self.assert_resolves_to_control(status.value, status)

        for label, status in _CONTROL_STATUS_LABELS.items():
            self.assert_resolves_to_control(label, status)

        for label, status in _PRESCRIPTION_STATUS_LABELS.items():
            self.assertEqual(
                resolve_status(normalize_label(label)).prescription, status, label
            )

    def test_spelling_variants_reach_the_same_status(self):
        for label in [
            "PV dressé",
            "pv dresse",
            "  PV   DRESSÉ  ",
            "PV dressé.",
            "«PV dressé»",
            "PV-dressé",
            "PV\u00a0dressé",  # non-breaking space
            "PV\u200b dressé",  # zero-width space next to a real one
            "PV dressé\u200b",
            "PV dressé\ufeff",  # BOM pasted mid-cell
            "Procès verbal dressé",
            "PROCÈS-VERBAL DRESSÉ",
            "official_report_drawn_up",
        ]:
            self.assert_resolves_to_control(
                label, DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP
            )

    def test_plural_spellings_reach_the_same_status(self):
        for label in [
            "Astreinte administrative",
            "Astreinte Administratives",
            "Astreintes administratives",
        ]:
            self.assert_resolves_to_control(
                label, DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT
            )

        for label in [
            "Rapport de constatations rédigé",
            "Rapport de constatation redigé",
            "RAPPORT DE CONSTATATION REDIGE",
        ]:
            self.assert_resolves_to_control(
                label, DetectionControlStatus.OBSERVARTION_REPORT_REDACTED
            )

    def test_placeholder_values_normalize_to_nothing(self):
        for label in ["", "   ", "-", " - ", "...", "\u00a0", "\u200b", "()"]:
            self.assertEqual(normalize_label(label), "", repr(label))

    def test_unrecognised_labels_are_not_guessed(self):
        for label in ["PV", "En cours", "Rapport", "N/A", "Astreinte"]:
            self.assertIsNone(resolve_status(normalize_label(label)), label)

    def test_colliding_labels_are_rejected_at_build_time(self):
        with self.assertRaises(ValueError):
            _build_label_map(
                {"OFFICIAL_REPORT_DRAWN_UP": DetectionControlStatus.JUGEMENT},
                DetectionControlStatus,
            )


class ImportControlStatusesCommandTests(BaseTestCase):
    def setUp(self):
        super().setUp()

        # the command writes its report CSVs to the working directory
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        previous_cwd = os.getcwd()
        os.chdir(tmp_dir)
        self.addCleanup(os.chdir, previous_cwd)
        self.tmp_dir = tmp_dir

        self.commune = create_montpellier_commune()
        self.tile = create_tile()
        self.tile_set = create_tile_set(name="2024")
        self.user = create_admin(email=USER_EMAIL)

    def write_csv(self, rows, columns=None, encoding="utf-8") -> str:
        path = os.path.join(self.tmp_dir, "statuses.csv")
        with open(path, "w", newline="", encoding=encoding) as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(columns or COLUMNS)
            writer.writerows(rows)
        return path

    def create_detection_on_parcel(
        self,
        parcel,
        detection_object=None,
        tile_set=None,
        control_status=DetectionControlStatus.NOT_CONTROLLED,
        validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
        prescription_status=DetectionPrescriptionStatus.PRESCRIBED,
        **kwargs,
    ):
        if detection_object is None:
            detection_object = create_detection_object(parcel=parcel)

        detection_data = create_detection_data(
            detection_control_status=control_status,
            detection_validation_status=validation_status,
            detection_prescription_status=prescription_status,
        )
        return create_detection(
            detection_object=detection_object,
            tile=self.tile,
            tile_set=tile_set or self.tile_set,
            detection_data=detection_data,
            **kwargs,
        )

    def test_applies_status_to_every_live_detection_of_the_parcel(self):
        # section "0B" in database, "B" in the CSV
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection_object = create_detection_object(parcel=parcel)
        first = self.create_detection_on_parcel(
            parcel, detection_object=detection_object
        )
        second = self.create_detection_on_parcel(
            parcel,
            detection_object=detection_object,
            tile_set=create_tile_set(name="2023"),
        )
        other_object_detection = self.create_detection_on_parcel(parcel)
        untouched = self.create_detection_on_parcel(
            create_parcel(commune=self.commune, id_parcellaire="000B0999")
        )

        csv_path = self.write_csv([[MONTPELLIER_INSEE, "B", "412", "PV dressé"]])
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        for detection in (first, second, other_object_detection):
            detection_data = DetectionData.objects.get(id=detection.detection_data_id)
            self.assertEqual(
                detection_data.detection_control_status,
                DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
            )
            # set_detection_control_status side effects
            self.assertEqual(
                detection_data.detection_validation_status,
                DetectionValidationStatus.SUSPECT,
            )
            self.assertEqual(
                detection_data.detection_prescription_status,
                DetectionPrescriptionStatus.NOT_PRESCRIBED,
            )

        untouched_data = DetectionData.objects.get(id=untouched.detection_data_id)
        self.assertEqual(
            untouched_data.detection_control_status,
            DetectionControlStatus.NOT_CONTROLLED,
        )

    def test_label_matching_ignores_case_accents_and_spacing(self):
        parcels = {
            "REMIS  EN  ETAT": DetectionControlStatus.REHABILITATED,
            "contrôlé terrain": DetectionControlStatus.CONTROLLED_FIELD,
            "Procès verbal dressé": DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
            "Astreinte Administratives": DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
            "Rapport de constatation redigé": DetectionControlStatus.OBSERVARTION_REPORT_REDACTED,
            # a status re-exported from the app comes back as its enum value
            "PRIOR_LETTER_SENT": DetectionControlStatus.PRIOR_LETTER_SENT,
        }

        rows = []
        detections = {}
        for index, label in enumerate(parcels):
            parcel = create_parcel(
                commune=self.commune, id_parcellaire=f"000B{index:04d}"
            )
            detections[label] = self.create_detection_on_parcel(parcel)
            rows.append([MONTPELLIER_INSEE, "B", str(index), label])

        csv_path = self.write_csv(rows)
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        for label, expected_status in parcels.items():
            detection_data = DetectionData.objects.get(
                id=detections[label].detection_data_id
            )
            self.assertEqual(
                detection_data.detection_control_status, expected_status, label
            )

    def test_prescription_label_only_touches_prescription(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(
            parcel,
            control_status=DetectionControlStatus.CONTROLLED_FIELD,
            validation_status=DetectionValidationStatus.SUSPECT,
            prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED,
        )

        csv_path = self.write_csv([[MONTPELLIER_INSEE, "B", "412", "Prescrit"]])
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(
            detection_data.detection_prescription_status,
            DetectionPrescriptionStatus.PRESCRIBED,
        )
        self.assertEqual(
            detection_data.detection_control_status,
            DetectionControlStatus.CONTROLLED_FIELD,
        )

    def test_unknown_status_is_reported_and_writes_nothing(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(parcel)

        csv_path = self.write_csv([[MONTPELLIER_INSEE, "B", "412", "À la mer"]])
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(
            detection_data.detection_control_status,
            DetectionControlStatus.NOT_CONTROLLED,
        )
        self.assertEqual(len(self.report_files("unknown_statuses")), 1)

    def test_placeholder_status_counts_as_no_status(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(parcel)

        csv_path = self.write_csv([[MONTPELLIER_INSEE, "B", "412", " - "]])
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(
            detection_data.detection_control_status,
            DetectionControlStatus.NOT_CONTROLLED,
        )
        self.assertEqual(self.report_files("unknown_statuses"), [])

    def test_unknown_parcel_is_reported(self):
        csv_path = self.write_csv([[MONTPELLIER_INSEE, "B", "412", "Remis en état"]])
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        self.assertEqual(len(self.report_files("parcels_not_found")), 1)

    def test_last_row_wins_for_a_repeated_parcel(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(parcel)

        csv_path = self.write_csv(
            [
                [MONTPELLIER_INSEE, "B", "412", "Contrôlé terrain"],
                [MONTPELLIER_INSEE, "B", "412", "Remis en état"],
            ]
        )
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(
            detection_data.detection_control_status,
            DetectionControlStatus.REHABILITATED,
        )

    def test_dry_run_writes_nothing(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(parcel)

        csv_path = self.write_csv([[MONTPELLIER_INSEE, "B", "412", "Remis en état"]])
        call_command(
            "import_control_statuses",
            csv_path=csv_path,
            user_email=USER_EMAIL,
            dry_run=True,
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(
            detection_data.detection_control_status,
            DetectionControlStatus.NOT_CONTROLLED,
        )

    def test_soft_deleted_rows_are_left_alone(self):
        deleted_parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        on_deleted_parcel = self.create_detection_on_parcel(deleted_parcel)
        deleted_parcel.deleted = True
        deleted_parcel.save()

        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0413")
        deleted_object = create_detection_object(parcel=parcel)
        on_deleted_object = self.create_detection_on_parcel(
            parcel, detection_object=deleted_object
        )
        deleted_object.deleted = True
        deleted_object.save()

        deleted_detection = self.create_detection_on_parcel(parcel, deleted=True)

        csv_path = self.write_csv(
            [
                [MONTPELLIER_INSEE, "B", "412", "Remis en état"],
                [MONTPELLIER_INSEE, "B", "413", "Remis en état"],
            ]
        )
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        for detection in (on_deleted_parcel, on_deleted_object, deleted_detection):
            detection_data = DetectionData.objects.get(id=detection.detection_data_id)
            self.assertEqual(
                detection_data.detection_control_status,
                DetectionControlStatus.NOT_CONTROLLED,
            )

    def test_already_up_to_date_detection_is_not_saved(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(
            parcel,
            control_status=DetectionControlStatus.REHABILITATED,
            validation_status=DetectionValidationStatus.SUSPECT,
            prescription_status=DetectionPrescriptionStatus.PRESCRIBED,
        )
        updated_at = DetectionData.objects.get(
            id=detection.detection_data_id
        ).updated_at

        csv_path = self.write_csv([[MONTPELLIER_INSEE, "B", "412", "Remis en état"]])
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(detection_data.updated_at, updated_at)

    def test_date_sets_the_update_date_and_the_author(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(parcel)

        csv_path = self.write_csv(
            [[MONTPELLIER_INSEE, "B", "412", "Contrôlé terrain", "12/03/2025"]],
            columns=COLUMNS_WITH_DATE,
        )
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(detection_data.user_last_update_id, self.user.id)
        # midday UTC, so every timezone the app serves displays 12/03/2025
        self.assertEqual(
            detection_data.updated_at, datetime(2025, 3, 12, 12, 0, tzinfo=UTC)
        )
        # not a PV: the official report date stays empty
        self.assertIsNone(detection_data.official_report_date)

    def test_date_on_a_pv_row_also_sets_the_official_report_date(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(parcel)

        csv_path = self.write_csv(
            [[MONTPELLIER_INSEE, "B", "412", "PV dressé", "2025-03-12"]],
            columns=COLUMNS_WITH_DATE,
        )
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(detection_data.official_report_date, date(2025, 3, 12))
        self.assertEqual(
            detection_data.updated_at, datetime(2025, 3, 12, 12, 0, tzinfo=UTC)
        )

    def test_official_report_date_alone_is_enough_to_count_as_a_change(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(
            parcel,
            control_status=DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
            validation_status=DetectionValidationStatus.SUSPECT,
            prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED,
        )

        csv_path = self.write_csv(
            [[MONTPELLIER_INSEE, "B", "412", "PV dressé", "12/03/2025 00:00"]],
            columns=COLUMNS_WITH_DATE,
        )
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(detection_data.official_report_date, date(2025, 3, 12))

    def test_row_with_an_invalid_date_is_skipped(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(parcel)

        csv_path = self.write_csv(
            [[MONTPELLIER_INSEE, "B", "412", "Remis en état", "mars 2025"]],
            columns=COLUMNS_WITH_DATE,
        )
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(
            detection_data.detection_control_status,
            DetectionControlStatus.NOT_CONTROLLED,
        )

    def test_empty_date_cell_leaves_the_update_date_alone(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(parcel)

        csv_path = self.write_csv(
            [[MONTPELLIER_INSEE, "B", "412", "Remis en état", ""]],
            columns=COLUMNS_WITH_DATE,
        )
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(
            detection_data.detection_control_status,
            DetectionControlStatus.REHABILITATED,
        )
        self.assertEqual(detection_data.user_last_update_id, self.user.id)
        self.assertGreater(detection_data.updated_at, datetime(2026, 1, 1, tzinfo=UTC))

    def test_unknown_user_aborts(self):
        csv_path = self.write_csv([[MONTPELLIER_INSEE, "B", "412", "Remis en état"]])

        with self.assertRaises(CommandError):
            call_command(
                "import_control_statuses",
                csv_path=csv_path,
                user_email="nobody@example.com",
            )

    def test_missing_column_aborts(self):
        csv_path = self.write_csv(
            [[MONTPELLIER_INSEE, "B", "412"]],
            columns=["COM_INSEE", "PARCELLE_SECTION", "PARCELLE_NUM"],
        )

        with self.assertRaises(CommandError):
            call_command(
                "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
            )

    def test_empty_csv_aborts(self):
        csv_path = self.write_csv([])

        with self.assertRaises(CommandError):
            call_command(
                "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
            )

    def test_excel_bom_and_padded_headers_are_accepted(self):
        parcel = create_parcel(commune=self.commune, id_parcellaire="000B0412")
        detection = self.create_detection_on_parcel(parcel)

        csv_path = self.write_csv(
            [[MONTPELLIER_INSEE, "B", "412", "Remis en état"]],
            columns=[
                " COM_INSEE",
                "PARCELLE_SECTION ",
                "PARCELLE_NUM",
                "STATUT_CONTROLE",
            ],
            encoding="utf-8-sig",
        )
        call_command(
            "import_control_statuses", csv_path=csv_path, user_email=USER_EMAIL
        )

        detection_data = DetectionData.objects.get(id=detection.detection_data_id)
        self.assertEqual(
            detection_data.detection_control_status,
            DetectionControlStatus.REHABILITATED,
        )

    def report_files(self, kind: str):
        return [
            name
            for name in os.listdir(self.tmp_dir)
            if name.startswith(f"import_control_statuses_{kind}-")
        ]
