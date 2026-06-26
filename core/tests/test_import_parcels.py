"""Tests for the import_parcels command's core logic (import_department_parcels).

The HTTP download is bypassed: the function is fed synthetic Etalab-shaped
features directly, so these tests cover the parts that can actually break —
upsert-by-id_parcellaire, department-scoped stale deletion, unknown-commune
skipping, and DetectionObject.parcel link preservation.
"""

from unittest.mock import MagicMock, patch

from django.core.management import call_command

from core.management.commands.import_parcels import import_department_parcels
from core.models.parcel import Parcel
from core.tests.base import BaseTestCase
from core.tests.fixtures.detection_data import create_detection_object
from core.tests.fixtures.geo_data import (
    create_beziers_commune,
    create_gard_department,
    create_herault_department,
    create_montpellier_commune,
    create_nimes_commune,
)


def make_feature(
    id_parcellaire,
    commune_iso,
    lon=3.88,
    lat=43.61,
    contenance=1000,
    updated="2026-03-01",
    numero="0001",
    prefixe="000",
    section="0A",
    arpente=False,
):
    size = 0.001
    coords = [
        [
            [lon - size, lat - size],
            [lon + size, lat - size],
            [lon + size, lat + size],
            [lon - size, lat + size],
            [lon - size, lat - size],
        ]
    ]
    return {
        "type": "Feature",
        "id": id_parcellaire,
        "geometry": {"type": "Polygon", "coordinates": coords},
        "properties": {
            "id": id_parcellaire,
            "commune": commune_iso,
            "prefixe": prefixe,
            "section": section,
            "numero": numero,
            "contenance": contenance,
            "arpente": arpente,
            "created": "2020-01-01",
            "updated": updated,
        },
    }


class ImportDepartmentParcelsTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.herault = create_herault_department()
        self.montpellier = create_montpellier_commune(department=self.herault)
        self.beziers = create_beziers_commune(department=self.herault)

    def test_creates_parcels_and_links_commune(self):
        features = [
            make_feature("34172000A0001", "34172", numero="0001"),
            make_feature("34032000B0042", "34032", numero="0042", section="0B"),
        ]
        upserted, deleted, skipped = import_department_parcels("34", features)

        self.assertEqual((upserted, deleted, skipped), (2, 0, 0))
        self.assertEqual(Parcel.objects.count(), 2)
        parcel = Parcel.objects.get(id_parcellaire="34032000B0042")
        self.assertEqual(parcel.commune, self.beziers)
        self.assertEqual(parcel.num_parcel, 42)  # leading zeros stripped
        self.assertEqual(parcel.section, "0B")

    def test_upsert_is_idempotent_and_refreshes(self):
        import_department_parcels(
            "34", [make_feature("34172000A0001", "34172", contenance=1000)]
        )
        parcel_id = Parcel.objects.get(id_parcellaire="34172000A0001").id

        upserted, deleted, skipped = import_department_parcels(
            "34", [make_feature("34172000A0001", "34172", contenance=2500)]
        )

        self.assertEqual((upserted, deleted, skipped), (1, 0, 0))
        self.assertEqual(Parcel.objects.count(), 1)  # no duplicate
        parcel = Parcel.objects.get(id_parcellaire="34172000A0001")
        self.assertEqual(parcel.id, parcel_id)  # same row (PK preserved)
        self.assertEqual(parcel.contenance, 2500)  # refreshed in place

    def test_deletes_stale_parcels_scoped_to_department(self):
        # A parcel in another department must survive a Hérault import.
        gard = create_gard_department()
        create_nimes_commune(department=gard)
        import_department_parcels("30", [make_feature("30189000A0001", "30189")])

        import_department_parcels("34", [make_feature("34172000A0001", "34172")])
        # Re-run for 34 without the first parcel, with a new one.
        upserted, deleted, skipped = import_department_parcels(
            "34", [make_feature("34172000A0002", "34172", numero="0002")]
        )

        self.assertEqual(deleted, 1)
        self.assertFalse(Parcel.objects.filter(id_parcellaire="34172000A0001").exists())
        self.assertTrue(Parcel.objects.filter(id_parcellaire="34172000A0002").exists())
        # Gard parcel untouched.
        self.assertTrue(Parcel.objects.filter(id_parcellaire="30189000A0001").exists())

    def test_skips_features_with_unknown_commune(self):
        features = [
            make_feature("34172000A0001", "34172"),
            make_feature("99999000A0001", "99999"),  # commune not in DB
        ]
        upserted, deleted, skipped = import_department_parcels("34", features)

        self.assertEqual((upserted, skipped), (1, 1))
        self.assertEqual(Parcel.objects.count(), 1)
        self.assertFalse(Parcel.objects.filter(id_parcellaire="99999000A0001").exists())

    def test_empty_dataset_does_not_wipe_existing_parcels(self):
        import_department_parcels("34", [make_feature("34172000A0001", "34172")])

        upserted, deleted, skipped = import_department_parcels("34", [])

        self.assertEqual((upserted, deleted), (0, 0))
        self.assertTrue(Parcel.objects.filter(id_parcellaire="34172000A0001").exists())

    def test_upsert_keeps_detection_link_but_stale_delete_nulls_it(self):
        import_department_parcels("34", [make_feature("34172000A0001", "34172")])
        parcel = Parcel.objects.get(id_parcellaire="34172000A0001")
        detection_object = create_detection_object(
            parcel=parcel, commune=self.montpellier
        )

        # Upsert: same parcel still present → link preserved.
        import_department_parcels(
            "34", [make_feature("34172000A0001", "34172", contenance=42)]
        )
        detection_object.refresh_from_db()
        self.assertEqual(detection_object.parcel_id, parcel.id)

        # Stale delete: parcel gone from dataset → SET_NULL on the link.
        import_department_parcels(
            "34", [make_feature("34172000A0009", "34172", numero="0009")]
        )
        detection_object.refresh_from_db()
        self.assertIsNone(detection_object.parcel_id)

    @patch("core.management.commands.import_parcels.get_data_parcels")
    def test_handle_dry_run_persists_nothing(self, mock_get):
        mock_get.return_value = (MagicMock(), [make_feature("34172000A0001", "34172")])

        call_command("import_parcels", "--department-code", "34", "--dry-run")

        self.assertEqual(Parcel.objects.count(), 0)

    @patch("core.management.commands.import_parcels.get_data_parcels")
    def test_handle_persists_and_relinks_only_when_pruning(self, mock_get):
        mock_get.return_value = (MagicMock(), [make_feature("34172000A0001", "34172")])
        # First import: nothing pruned → no detection re-link triggered.
        with patch("core.management.commands.import_parcels.call_command") as mock_cc:
            call_command("import_parcels", "--department-code", "34")
        self.assertEqual(Parcel.objects.count(), 1)
        mock_cc.assert_not_called()

        # Re-import without the first parcel → prune happens → re-link triggered.
        mock_get.return_value = (
            MagicMock(),
            [make_feature("34172000A0002", "34172", numero="0002")],
        )
        with patch("core.management.commands.import_parcels.call_command") as mock_cc:
            call_command("import_parcels", "--department-code", "34")
        self.assertEqual(Parcel.objects.count(), 1)  # A1 pruned, A2 inserted
        mock_cc.assert_called_once_with(
            "update_detection_parcels", department_code="34"
        )

    @patch("core.management.commands.import_parcels.DeployedDataService.refresh_cache")
    @patch("core.management.commands.import_parcels.get_data_parcels")
    def test_handle_refreshes_deployed_data_cache_on_persist(
        self, mock_get, mock_refresh
    ):
        mock_get.return_value = (MagicMock(), [make_feature("34172000A0001", "34172")])

        call_command("import_parcels", "--department-code", "34")

        mock_refresh.assert_called_once()

    @patch("core.management.commands.import_parcels.DeployedDataService.refresh_cache")
    @patch("core.management.commands.import_parcels.get_data_parcels")
    def test_handle_dry_run_does_not_refresh_deployed_data_cache(
        self, mock_get, mock_refresh
    ):
        mock_get.return_value = (MagicMock(), [make_feature("34172000A0001", "34172")])

        call_command("import_parcels", "--department-code", "34", "--dry-run")

        mock_refresh.assert_not_called()
