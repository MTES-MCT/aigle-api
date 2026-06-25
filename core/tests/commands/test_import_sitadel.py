"""Tests for the `import_sitadel` management command.

The command reconciles Sitadel building-permit rows (read from a CSV) against
parcels, and — when a parcel's detections were never controlled by a user —
marks those detections LEGITIMATE and records a DetectionAuthorization.

The focus here is the user-control guard: a parcel that has *any* detection
whose control status is not NOT_CONTROLLED must be left entirely untouched, so
the import never overwrites a manual control decision.
"""

import csv
import datetime
import io
import tempfile
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import SimpleTestCase
from django.utils import timezone

from core.management.commands.import_sitadel import (
    Command,
    _select_autorisations_datafiles,
)

from core.models.detection_authorization import DetectionAuthorization
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
    DetectionValidationStatusChangeReason,
)
from core.models.parcel import Parcel
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_tile,
    create_tile_set,
)
from core.tests.fixtures.geo_data import (
    create_herault_department,
    create_montpellier_commune,
    create_occitanie_region,
)

CSV_FIELDS = [
    "DEP_CODE",
    "COMM",
    "TYPE_DAU",
    "NUM_DAU",
    "ETAT_DAU",
    "DATE_REELLE_AUTORISATION",
    "DPC_DERN",
    "SEC_CADASTRE1",
    "NUM_CADASTRE1",
    "SEC_CADASTRE2",
    "NUM_CADASTRE2",
    "SEC_CADASTRE3",
    "NUM_CADASTRE3",
]


def _sitadel_row(comm, section, num_parcel, num_dau, date="2024-01-15", etat="2"):
    return {
        "DEP_CODE": comm[:2],
        "COMM": comm,
        "TYPE_DAU": "PC",
        "NUM_DAU": num_dau,
        "ETAT_DAU": etat,
        "DATE_REELLE_AUTORISATION": date,
        "DPC_DERN": "2024-02",
        "SEC_CADASTRE1": section,
        "NUM_CADASTRE1": str(num_parcel),
        "SEC_CADASTRE2": "",
        "NUM_CADASTRE2": "",
        "SEC_CADASTRE3": "",
        "NUM_CADASTRE3": "",
    }


def _write_csv(rows, label_header=False):
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    if label_header:
        # New Sitadel format prepends a human-readable label row before the codes.
        csv.writer(tmp, delimiter=";").writerow([f"Libellé {f}" for f in CSV_FIELDS])
    writer = csv.DictWriter(tmp, fieldnames=CSV_FIELDS, delimiter=";")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    tmp.flush()
    tmp.close()
    return tmp.name


def _csv_reader(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, delimiter=";")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buf.seek(0)
    return csv.DictReader(buf, delimiter=";")


class ExtractDataFromCsvFilterTests(SimpleTestCase):
    """The --filter-dpts / --filter-coms row filtering (replaces the old
    standalone extract_sitadel.py pre-pass)."""

    def test_filter_dpts_uses_dep_code_column_not_comm_prefix(self):
        # Overseas: DEP_CODE='974' but COMM[:2]='97' — the row must survive.
        row = _sitadel_row("97411", "AB", 12, "PC1")
        row["DEP_CODE"] = "974"
        data = Command.extract_data_from_csv(
            _csv_reader([row]), filter_coms=None, filter_dpts=["974"]
        )
        self.assertEqual(len(data), 1)

    def test_filter_dpts_excludes_non_matching(self):
        row = _sitadel_row("34172", "AB", 12, "PC1")  # DEP_CODE='34'
        data = Command.extract_data_from_csv(
            _csv_reader([row]), filter_coms=None, filter_dpts=["31"]
        )
        self.assertEqual(data, [])

    def test_filter_coms(self):
        rows = [
            _sitadel_row("34172", "AB", 12, "PC1"),
            _sitadel_row("34173", "AB", 13, "PC2"),
        ]
        data = Command.extract_data_from_csv(
            _csv_reader(rows), filter_coms=["34172"], filter_dpts=None
        )
        self.assertEqual([d.data_input["COMM"] for d in data], ["34172"])


class SelectAutorisationsDatafilesTests(SimpleTestCase):
    """The DiDo auto-download picks both 'autorisations' datafiles at their latest
    millesime, and ignores the permis d'aménager / démolir siblings."""

    def test_selects_both_autorisations_at_latest_millesime(self):
        dataset = {
            "datafiles": [
                {
                    "title": "Liste des autorisations d'urbanisme créant des logements",
                    "rid": "rid-log",
                    "millesimes": [{"millesime": "2026-04"}, {"millesime": "2026-05"}],
                },
                {
                    "title": "Liste des autorisations d'urbanisme créant des locaux non résidentiels",
                    "rid": "rid-loc",
                    "millesimes": [{"millesime": "2026-05"}],
                },
                {
                    "title": "Liste des permis d'aménager",
                    "rid": "rid-amng",
                    "millesimes": [{"millesime": "2026-05"}],
                },
                {
                    "title": "Liste des permis de démolir",
                    "rid": "rid-demo",
                    "millesimes": [{"millesime": "2026-05"}],
                },
            ]
        }
        self.assertEqual(
            sorted(_select_autorisations_datafiles(dataset)),
            [
                (
                    "Liste des autorisations d'urbanisme créant des locaux non résidentiels",
                    "rid-loc",
                    "2026-05",
                ),
                (
                    "Liste des autorisations d'urbanisme créant des logements",
                    "rid-log",
                    "2026-05",
                ),
            ],
        )

    def test_skips_datafiles_without_millesime(self):
        dataset = {
            "datafiles": [
                {
                    "title": "Liste des autorisations d'urbanisme créant des logements",
                    "rid": "rid-log",
                    "millesimes": [],
                }
            ]
        }
        self.assertEqual(_select_autorisations_datafiles(dataset), [])


class ImportSitadelCommandTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.region = create_occitanie_region()
        self.department = create_herault_department(region=self.region)
        self.commune = create_montpellier_commune(department=self.department)
        self.tile_set = create_tile_set(name="Sitadel TS")
        self.tile = create_tile(x=1, y=1, z=18)

    def _create_parcel(self, section, num_parcel):
        return Parcel.objects.create(
            id_parcellaire=f"34172{section}{num_parcel:04d}",
            prefix="000",
            section=section,
            num_parcel=num_parcel,
            contenance=1000,
            arpente=False,
            geometry=Point(3.88, 43.61, srid=4326).buffer(0.001),
            commune=self.commune,
            refreshed_at=timezone.now(),
        )

    def _create_detection(self, parcel, control_status):
        detection_object = create_detection_object(parcel=parcel, commune=self.commune)
        detection_data = create_detection_data(
            detection_control_status=control_status,
            detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
        )
        create_detection(
            detection_object=detection_object,
            tile=self.tile,
            tile_set=self.tile_set,
            detection_data=detection_data,
        )
        return detection_data

    def test_uncontrolled_detection_is_marked_legitimate(self):
        """Happy path: a parcel with only NOT_CONTROLLED detections is updated."""
        parcel = self._create_parcel("CD", 200)
        detection_data = self._create_detection(
            parcel, DetectionControlStatus.NOT_CONTROLLED
        )

        csv_path = _write_csv([_sitadel_row("34172", "CD", 200, "PC456")])
        call_command("import_sitadel", file_csv_path=csv_path, persist_data=True)

        detection_data.refresh_from_db()
        self.assertEqual(
            detection_data.detection_validation_status,
            DetectionValidationStatus.LEGITIMATE,
        )
        self.assertEqual(
            detection_data.detection_validation_status_change_reason,
            DetectionValidationStatusChangeReason.SITADEL,
        )
        authorization = DetectionAuthorization.objects.get(
            detection_data=detection_data
        )
        self.assertEqual(authorization.authorization_id, "PC456")
        self.assertEqual(authorization.authorization_date, datetime.date(2024, 1, 15))

    def test_controlled_detection_is_not_updated(self):
        """A parcel whose detection was controlled by a user is left untouched."""
        parcel = self._create_parcel("AB", 100)
        detection_data = self._create_detection(
            parcel, DetectionControlStatus.CONTROLLED_FIELD
        )

        csv_path = _write_csv([_sitadel_row("34172", "AB", 100, "PC123")])
        call_command("import_sitadel", file_csv_path=csv_path, persist_data=True)

        detection_data.refresh_from_db()
        self.assertEqual(
            detection_data.detection_validation_status,
            DetectionValidationStatus.DETECTED_NOT_VERIFIED,
        )
        self.assertIsNone(detection_data.detection_validation_status_change_reason)
        self.assertFalse(DetectionAuthorization.objects.exists())

    def test_one_controlled_detection_excludes_the_whole_parcel(self):
        """The guard is parcel-level: a single controlled detection protects every
        detection on that parcel, even a sibling that is still NOT_CONTROLLED.

        This is the regression guard — a naive join filter on
        ``detection_control_status=NOT_CONTROLLED`` would match the uncontrolled
        sibling and wrongly update the parcel.
        """
        parcel = self._create_parcel("EF", 300)
        controlled = self._create_detection(
            parcel, DetectionControlStatus.CONTROLLED_FIELD
        )
        uncontrolled = self._create_detection(
            parcel, DetectionControlStatus.NOT_CONTROLLED
        )

        csv_path = _write_csv([_sitadel_row("34172", "EF", 300, "PC789")])
        call_command("import_sitadel", file_csv_path=csv_path, persist_data=True)

        controlled.refresh_from_db()
        uncontrolled.refresh_from_db()
        for detection_data in (controlled, uncontrolled):
            self.assertEqual(
                detection_data.detection_validation_status,
                DetectionValidationStatus.DETECTED_NOT_VERIFIED,
            )
        self.assertFalse(
            DetectionAuthorization.objects.filter(authorization_id="PC789").exists()
        )

    def test_two_header_rows_new_sitadel_format(self):
        """New Sitadel export prepends a label row before the technical codes;
        the command skips it and still reconciles parcels."""
        parcel = self._create_parcel("IJ", 500)
        detection_data = self._create_detection(
            parcel, DetectionControlStatus.NOT_CONTROLLED
        )

        csv_path = _write_csv(
            [_sitadel_row("34172", "IJ", 500, "PC500")], label_header=True
        )
        call_command("import_sitadel", file_csv_path=csv_path, persist_data=True)

        detection_data.refresh_from_db()
        self.assertEqual(
            detection_data.detection_validation_status,
            DetectionValidationStatus.LEGITIMATE,
        )
        self.assertEqual(
            DetectionAuthorization.objects.get(
                detection_data=detection_data
            ).authorization_id,
            "PC500",
        )

    def test_dry_run_does_not_persist(self):
        """Without persist_data, nothing is written."""
        parcel = self._create_parcel("GH", 400)
        detection_data = self._create_detection(
            parcel, DetectionControlStatus.NOT_CONTROLLED
        )

        csv_path = _write_csv([_sitadel_row("34172", "GH", 400, "PC999")])
        call_command("import_sitadel", file_csv_path=csv_path, persist_data=False)

        detection_data.refresh_from_db()
        self.assertEqual(
            detection_data.detection_validation_status,
            DetectionValidationStatus.DETECTED_NOT_VERIFIED,
        )
        self.assertFalse(DetectionAuthorization.objects.exists())

    @patch("core.management.commands.import_sitadel.DeployedDataService.refresh_cache")
    def test_persisting_import_refreshes_deployed_data_cache(self, mock_refresh):
        """Regression: the deployed-data dashboard reads the SITADEL change reason
        (sitadel_updated_parcels_count) from a version-gated cache that no import used
        to bump, so it kept serving pre-import figures. A persisting import now refreshes
        it exactly once."""
        parcel = self._create_parcel("KL", 600)
        self._create_detection(parcel, DetectionControlStatus.NOT_CONTROLLED)

        csv_path = _write_csv([_sitadel_row("34172", "KL", 600, "PC600")])
        call_command("import_sitadel", file_csv_path=csv_path, persist_data=True)

        mock_refresh.assert_called_once()

    @patch("core.management.commands.import_sitadel.DeployedDataService.refresh_cache")
    def test_dry_run_does_not_refresh_deployed_data_cache(self, mock_refresh):
        parcel = self._create_parcel("MN", 700)
        self._create_detection(parcel, DetectionControlStatus.NOT_CONTROLLED)

        csv_path = _write_csv([_sitadel_row("34172", "MN", 700, "PC700")])
        call_command("import_sitadel", file_csv_path=csv_path, persist_data=False)

        mock_refresh.assert_not_called()

    @patch("core.management.commands.import_sitadel.DeployedDataService.refresh_cache")
    def test_import_with_no_changes_does_not_refresh(self, mock_refresh):
        """Nothing written (every match is a user-controlled, protected parcel) ->
        no needless full-dataset recompute."""
        parcel = self._create_parcel("OP", 800)
        self._create_detection(parcel, DetectionControlStatus.CONTROLLED_FIELD)

        csv_path = _write_csv([_sitadel_row("34172", "OP", 800, "PC800")])
        call_command("import_sitadel", file_csv_path=csv_path, persist_data=True)

        mock_refresh.assert_not_called()
