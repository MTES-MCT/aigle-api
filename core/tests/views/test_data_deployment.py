"""Tests for the data-deployment listing endpoint (utils/data-deployment/).

The endpoint reads the external `detections` schema (run / batch / zae_layer)
which doesn't exist in the test database, so each test provisions those tables
(DDL is rolled back with the surrounding test transaction). The listing is one
row per geozone (collectivity), not one per run.
"""

from datetime import date
from unittest.mock import patch

from django.db import connection
from django.utils import timezone

from core.models.geo_custom_zone import GeoCustomZone
from core.models.object_type_category import ObjectTypeCategory
from core.models.tile_set import TileSet, TileSetScheme, TileSetType
from core.models.user_group import UserGroup, UserGroupType
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import create_detection, create_tile_set
from core.tests.fixtures.geo_data import (
    create_herault_department,
    create_montpellier_commune,
    create_occitanie_region,
)
from core.tests.fixtures.users import create_regular_user, create_super_admin
from core.utils.run_command import COMMANDS_AND_PARAMETERS_MAP, parse_parameters

ENDPOINT = "/api/utils/data-deployment/"
RUN_ENDPOINT = "/api/utils/data-deployment/{geozone_id}/run/"
RUN_COMMAND_PATH = "core.services.data_deployment.CommandAsyncService.run_command_async"


def _provision_schema():
    with connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS detections")
        cursor.execute("DROP TABLE IF EXISTS detections.batch")
        cursor.execute("DROP TABLE IF EXISTS detections.run")
        cursor.execute("DROP TABLE IF EXISTS detections.zae_layer")
        cursor.execute(
            """
            CREATE TABLE detections.run (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                geozone_id bigint NULL,
                created_at timestamptz NULL,
                src_image_year bigint NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE detections.batch (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                batch_name varchar NULL,
                created_at timestamptz NULL,
                batch_tiles_url varchar NULL,
                run_id bigint NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE detections.zae_layer (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                layer_name varchar NULL,
                layer_type varchar NULL,
                layer_year int NULL,
                department_code varchar NULL,
                created_at timestamptz NULL
            )
            """
        )


def _insert_run(geozone_id, created_at="2024-01-01T00:00:00Z", src_image_year=2024):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO detections.run (geozone_id, created_at, src_image_year) "
            "VALUES (%s, %s, %s) RETURNING id",
            [geozone_id, created_at, src_image_year],
        )
        return cursor.fetchone()[0]


def _insert_batch(run_id, name, tiles_url=None, created_at="2024-01-01T00:00:00Z"):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO detections.batch (run_id, batch_name, batch_tiles_url, "
            "created_at) VALUES (%s, %s, %s, %s) RETURNING id",
            [run_id, name, tiles_url, created_at],
        )
        return cursor.fetchone()[0]


def _insert_zae(
    department_code,
    layer_type,
    layer_name,
    layer_year=2024,
    created_at="2024-01-01T00:00:00Z",
):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO detections.zae_layer (department_code, layer_type, "
            "layer_name, layer_year, created_at) VALUES (%s, %s, %s, %s, %s)",
            [department_code, layer_type, layer_name, layer_year, created_at],
        )


class DataDeploymentViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.region = create_occitanie_region()
        self.department = create_herault_department(region=self.region)
        self.commune = create_montpellier_commune(department=self.department)
        _provision_schema()

    def test_unauthenticated_returns_401(self):
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 401)

    def test_regular_user_returns_403(self):
        self.authenticate_user(create_regular_user())
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 403)

    def test_lists_geozone_with_batches_and_zae(self):
        run_id = _insert_run(self.department.id)
        _insert_batch(
            run_id,
            "batch-herault",
            tiles_url="s3://aigle-tiles/aerial/languedoc/2024_herault",
        )
        _insert_zae("34", "zfee", "ZFEE Hérault")
        _insert_zae("30", "zi", "Other department")  # must not appear

        self.authenticate_user(create_super_admin())
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["count"], 1)
        geozone = data["results"][0]
        self.assertEqual(geozone["uuid"], str(self.department.id))
        self.assertEqual(geozone["geozoneName"], "Hérault")

        batch = geozone["batches"][0]
        self.assertEqual(batch["name"], "batch-herault")
        self.assertEqual(
            batch["tilesUrl"],
            "https://tiles.aigle.beta.gouv.fr/aerial/languedoc/2024_herault/{z}/{x}/{y}.png",
        )
        self.assertEqual(batch["deployStatus"], "NOT_DEPLOYED")  # no detection imported

        self.assertEqual({z["name"] for z in geozone["zaeLayers"]}, {"ZFEE Hérault"})
        self.assertEqual(
            geozone["zaeLayers"][0]["typeName"], "Zones à fort enjeu environnemental"
        )
        # no GeoCustomZone with that name -> not deployed
        self.assertEqual(geozone["zaeLayers"][0]["deployStatus"], "NOT_DEPLOYED")
        self.assertTrue(geozone["zaeLayers"][0]["createdAt"].startswith("2024-01-01"))

    def test_multiple_runs_same_geozone_collapse_to_one_row(self):
        run_old = _insert_run(self.department.id, created_at="2024-01-01T00:00:00Z")
        _insert_batch(run_old, "batch-old")
        run_new = _insert_run(self.department.id, created_at="2024-06-01T00:00:00Z")
        _insert_batch(run_new, "batch-new")

        self.authenticate_user(create_super_admin())
        data = self.client.get(ENDPOINT).json()

        self.assertEqual(data["count"], 1)  # one row per geozone, not per run
        geozone = data["results"][0]
        self.assertTrue(geozone["createdAt"].startswith("2024-06"))  # latest run
        self.assertEqual(
            {b["name"] for b in geozone["batches"]}, {"batch-old", "batch-new"}
        )

    def test_commune_run_resolves_zae_via_parent_department(self):
        run_id = _insert_run(self.commune.id)
        _insert_batch(run_id, "batch-montpellier")
        _insert_zae("34", "zrf", "ZRF Hérault")

        self.authenticate_user(create_super_admin())
        geozone = self.client.get(ENDPOINT).json()["results"][0]
        self.assertEqual(geozone["geozoneName"], "Montpellier")
        self.assertEqual({z["name"] for z in geozone["zaeLayers"]}, {"ZRF Hérault"})

    def test_q_filters_geozones_by_batch_name(self):
        run_dept = _insert_run(self.department.id)
        _insert_batch(run_dept, "pools-2024")
        run_commune = _insert_run(self.commune.id)
        _insert_batch(run_commune, "caravans-2024")

        self.authenticate_user(create_super_admin())
        data = self.client.get(ENDPOINT, {"q": "pools"}).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["uuid"], str(self.department.id))

    def test_batch_created_at_min_filters_geozones(self):
        run_old = _insert_run(self.department.id)
        _insert_batch(run_old, "old", created_at="2023-01-01T00:00:00Z")
        run_new = _insert_run(self.commune.id)
        _insert_batch(run_new, "new", created_at="2024-06-01T00:00:00Z")

        self.authenticate_user(create_super_admin())
        data = self.client.get(ENDPOINT, {"batchCreatedAtMin": "2024-01-01"}).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["uuid"], str(self.commune.id))

    def test_batch_deployment_statuses(self):
        run_id = _insert_run(self.department.id)
        _insert_batch(run_id, "not-deployed")
        running = _insert_batch(run_id, "running")
        deployed = _insert_batch(run_id, "deployed")

        # detection exists, its tile set import hasn't finished -> DEPLOYMENT_RUNNING
        create_detection(
            batch_id=str(running),
            tile_set=create_tile_set(name="ts-running", last_import_ended_at=None),
        )
        # detection exists, its tile set import has finished -> DEPLOYED
        create_detection(
            batch_id=str(deployed),
            tile_set=create_tile_set(
                name="ts-deployed", last_import_ended_at=timezone.now()
            ),
        )

        self.authenticate_user(create_super_admin())
        batches = self.client.get(ENDPOINT).json()["results"][0]["batches"]
        status_by_name = {b["name"]: b["deployStatus"] for b in batches}
        self.assertEqual(status_by_name["not-deployed"], "NOT_DEPLOYED")
        self.assertEqual(status_by_name["running"], "DEPLOYMENT_RUNNING")
        self.assertEqual(status_by_name["deployed"], "DEPLOYED")

    def test_zae_deployment_status(self):
        run_id = _insert_run(self.department.id)
        _insert_batch(run_id, "batch")
        _insert_zae("34", "zfee", "Deployed zone")
        _insert_zae("34", "zrf", "Missing zone")

        # a GeoCustomZone imported from the zae layer (matched on import_layer_name,
        # not the admin-editable name) -> DEPLOYED
        GeoCustomZone.objects.create(
            name="Renamed by an admin",
            import_layer_name="Deployed zone",
            geometry=self.create_polygon(
                [(3.8, 43.5), (3.9, 43.5), (3.9, 43.6), (3.8, 43.6), (3.8, 43.5)]
            ),
        )

        self.authenticate_user(create_super_admin())
        zae_layers = self.client.get(ENDPOINT).json()["results"][0]["zaeLayers"]
        status_by_name = {z["name"]: z["deployStatus"] for z in zae_layers}
        self.assertEqual(status_by_name["Deployed zone"], "DEPLOYED")
        self.assertEqual(status_by_name["Missing zone"], "NOT_DEPLOYED")

    def test_malformed_filters_do_not_crash(self):
        run_id = _insert_run(self.department.id)
        _insert_batch(run_id, "batch")

        self.authenticate_user(create_super_admin())
        for bad_date in ("not-a-date", "2024-02-31"):  # regex miss AND calendar-invalid
            response = self.client.get(
                ENDPOINT,
                {"batchCreatedAtMin": bad_date, "limit": "-5", "offset": "-3"},
            )
            self.assertEqual(response.status_code, 200, bad_date)
            self.assertEqual(response.json()["count"], 1)  # bad date ignored


class DataDeploymentRunViewTests(BaseAPITestCase):
    """POST data-deployment/<geozone_id>/run/ — creates the per-batch TileSets and
    the Cabanisation UserGroup inline, then queues the import commands. The Celery
    dispatch (CommandAsyncService.run_command_async) is mocked so nothing is enqueued."""

    def setUp(self):
        super().setUp()
        self.region = create_occitanie_region()
        self.department = create_herault_department(region=self.region)  # insee_code 34
        self.commune = create_montpellier_commune(department=self.department)
        _provision_schema()

    def _create_cabanisation_category(self):
        return ObjectTypeCategory.objects.create(name="Cabanisation")

    def _url(self, geozone_id):
        return RUN_ENDPOINT.format(geozone_id=geozone_id)

    def test_run_unauthenticated_returns_401(self):
        response = self.client.post(self._url(self.department.id))
        self.assertEqual(response.status_code, 401)

    def test_run_regular_user_returns_403(self):
        self.authenticate_user(create_regular_user())
        response = self.client.post(self._url(self.department.id))
        self.assertEqual(response.status_code, 403)

    def test_run_department_creates_tilesets_usergroup_and_queues_commands(self):
        self._create_cabanisation_category()
        run_id = _insert_run(self.department.id, src_image_year=2024)
        batch_id = _insert_batch(
            run_id,
            "batch-herault",
            tiles_url="s3://aigle-tiles/aerial/languedoc/2024_herault",
        )

        self.authenticate_user(create_super_admin())
        with patch(RUN_COMMAND_PATH, return_value="task-uuid") as run_command:
            response = self.client.post(self._url(self.department.id))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["tileSetsCreated"], ["Hérault (34) 2024"])
        self.assertEqual(data["userGroupName"], "Cabanisation Hérault (34)")
        self.assertEqual(len(data["queuedCommands"]), 5)

        # TileSet: one per batch, BACKGROUND, xyz, dated to src_image_year, zoom 15-19
        tile_set = TileSet.objects.get(name="Hérault (34) 2024")
        self.assertEqual(tile_set.tile_set_type, TileSetType.BACKGROUND)
        self.assertEqual(tile_set.tile_set_scheme, TileSetScheme.xyz)
        self.assertEqual(tile_set.date, date(2024, 1, 1))
        self.assertEqual(tile_set.min_zoom, 15)
        self.assertEqual(tile_set.max_zoom, 19)
        self.assertEqual(
            tile_set.url,
            "https://tiles.aigle.beta.gouv.fr/aerial/languedoc/2024_herault/{z}/{x}/{y}.png",
        )
        self.assertTrue(tile_set.geo_zones.filter(id=self.department.id).exists())

        # UserGroup: DDTM (department), scoped to the geozone + Cabanisation category
        user_group = UserGroup.objects.get(name="Cabanisation Hérault (34)")
        self.assertEqual(user_group.user_group_type, UserGroupType.DDTM)
        self.assertTrue(user_group.geo_zones.filter(id=self.department.id).exists())
        self.assertTrue(
            user_group.object_type_categories.filter(name="Cabanisation").exists()
        )

        # Commands queued in dependency order with the right parameters
        calls = [
            (c.kwargs["command_name"], c.kwargs["parameters"])
            for c in run_command.call_args_list
        ]
        self.assertEqual(
            [name for name, _ in calls],
            [
                "import_custom_zones",
                "create_tile",
                "import_parcels",
                "import_detections",
                "import_sitadel",
            ],
        )
        params = dict(calls)
        self.assertEqual(params["import_custom_zones"], {"--department-code": "34"})
        self.assertEqual(
            params["create_tile"], {"--geozone-uuid": str(self.department.uuid)}
        )
        self.assertEqual(params["import_parcels"], {"--department-code": "34"})
        self.assertEqual(
            params["import_detections"],
            {"--tile-set-id": tile_set.id, "--batch-id": str(batch_id)},
        )
        self.assertEqual(
            params["import_sitadel"],
            {"--department-code": "34", "--persist-data": True},
        )

    def test_run_commune_uses_parent_department_and_collectivity_group(self):
        self._create_cabanisation_category()
        run_id = _insert_run(self.commune.id, src_image_year=2023)
        _insert_batch(
            run_id, "batch-mtp", tiles_url="s3://aigle-tiles/aerial/oc/2023_montpellier"
        )

        self.authenticate_user(create_super_admin())
        with patch(RUN_COMMAND_PATH, return_value="task-uuid") as run_command:
            response = self.client.post(self._url(self.commune.id))

        self.assertEqual(response.status_code, 200)
        # commune -> COLLECTIVITY group, tile set named after the commune
        user_group = UserGroup.objects.get(name="Cabanisation Montpellier (34172)")
        self.assertEqual(user_group.user_group_type, UserGroupType.COLLECTIVITY)
        self.assertTrue(
            TileSet.objects.filter(name="Montpellier (34172) 2023").exists()
        )

        # department-scoped commands use the commune's PARENT department insee_code
        params = dict(
            (c.kwargs["command_name"], c.kwargs["parameters"])
            for c in run_command.call_args_list
        )
        self.assertEqual(params["import_custom_zones"], {"--department-code": "34"})
        self.assertEqual(params["import_parcels"], {"--department-code": "34"})

    def test_run_missing_cabanisation_category_returns_400(self):
        run_id = _insert_run(self.department.id, src_image_year=2024)
        _insert_batch(run_id, "batch", tiles_url="s3://aigle-tiles/x/2024_y")

        self.authenticate_user(create_super_admin())
        with patch(RUN_COMMAND_PATH) as run_command:
            response = self.client.post(self._url(self.department.id))

        self.assertEqual(response.status_code, 400)
        self.assertIn("Cabanisation", response.json()["detail"])
        # the category is checked before any write/dispatch
        self.assertFalse(TileSet.objects.filter(name="Hérault (34) 2024").exists())
        run_command.assert_not_called()

    def test_run_skips_batches_without_tiles_url_or_year(self):
        self._create_cabanisation_category()
        run_with_year = _insert_run(self.department.id, src_image_year=2024)
        _insert_batch(run_with_year, "ok", tiles_url="s3://aigle-tiles/x/2024_y")
        run_no_year = _insert_run(self.department.id, src_image_year=None)
        _insert_batch(run_no_year, "no-year", tiles_url="s3://aigle-tiles/x/none")

        self.authenticate_user(create_super_admin())
        with patch(RUN_COMMAND_PATH, return_value="task-uuid"):
            data = self.client.post(self._url(self.department.id)).json()

        self.assertEqual(data["tileSetsCreated"], ["Hérault (34) 2024"])
        self.assertEqual({b["name"] for b in data["skippedBatches"]}, {"no-year"})

    def test_run_out_of_range_year_skips_batch_without_aborting(self):
        self._create_cabanisation_category()
        good = _insert_run(self.department.id, src_image_year=2024)
        _insert_batch(good, "ok", tiles_url="s3://aigle-tiles/x/2024_y")
        bad = _insert_run(self.department.id, src_image_year=99999)
        _insert_batch(bad, "bad-year", tiles_url="s3://aigle-tiles/x/bad")

        self.authenticate_user(create_super_admin())
        with patch(RUN_COMMAND_PATH, return_value="task-uuid"):
            data = self.client.post(self._url(self.department.id)).json()

        # the implausible year is skipped, the valid batch still deploys
        self.assertEqual(data["tileSetsCreated"], ["Hérault (34) 2024"])
        self.assertEqual({b["name"] for b in data["skippedBatches"]}, {"bad-year"})

    def test_run_tileset_url_conflict_returns_400(self):
        self._create_cabanisation_category()
        run_id = _insert_run(self.department.id, src_image_year=2024)
        _insert_batch(run_id, "batch", tiles_url="s3://aigle-tiles/x/2024_y")
        # a different TileSet already owns the url this batch would generate
        create_tile_set(
            name="Conflicting",
            url="https://tiles.aigle.beta.gouv.fr/x/2024_y/{z}/{x}/{y}.png",
        )

        self.authenticate_user(create_super_admin())
        with patch(RUN_COMMAND_PATH) as run_command:
            response = self.client.post(self._url(self.department.id))

        # IntegrityError is translated to a clean 400, not a 500
        self.assertEqual(response.status_code, 400)
        self.assertIn("conflict", response.json()["detail"].lower())
        run_command.assert_not_called()
        # the atomic block rolled back: no UserGroup left behind
        self.assertFalse(
            UserGroup.objects.filter(name="Cabanisation Hérault (34)").exists()
        )

    def test_run_nonexistent_geozone_returns_400(self):
        self.authenticate_user(create_super_admin())
        with patch(RUN_COMMAND_PATH) as run_command:
            response = self.client.post(self._url(99999999))
        self.assertEqual(response.status_code, 400)
        self.assertIn("not found", response.json()["detail"].lower())
        run_command.assert_not_called()

    def test_run_non_deployable_geozone_returns_400(self):
        # a region is a valid geozone but not a deployable type
        self._create_cabanisation_category()
        self.authenticate_user(create_super_admin())
        with patch(RUN_COMMAND_PATH) as run_command:
            response = self.client.post(self._url(self.region.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("not deployable", response.json()["detail"].lower())
        run_command.assert_not_called()

    def test_queued_command_flags_match_real_argparse_specs(self):
        """The flags we queue must actually exist on each command. parse_parameters does
        NOT reject unknown/typo'd non-required flags, so assert membership against the
        introspected argparse spec directly (the source of truth the run-command UI uses)."""
        expected_flags = {
            "import_custom_zones": {"--department-code"},
            "create_tile": {"--geozone-uuid"},
            "import_parcels": {"--department-code"},
            "import_detections": {"--tile-set-id", "--batch-id"},
            "import_sitadel": {"--department-code", "--persist-data"},
        }
        for command, flags in expected_flags.items():
            known = set(COMMANDS_AND_PARAMETERS_MAP[command])
            self.assertTrue(flags <= known, f"{command} is missing {flags - known}")

        # the dry-run trap: persist-data must coerce to boolean True, not a truthy string
        parsed = parse_parameters(
            "import_sitadel", {"--department-code": "34", "--persist-data": True}
        )
        self.assertIs(parsed["--persist-data"], True)
