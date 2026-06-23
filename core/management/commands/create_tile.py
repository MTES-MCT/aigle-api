import math
import time

from django.contrib.gis.db.models.functions import Envelope
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from core.management.base import CommandRunTrackerMixin

from core.constants.geo import SRID
from core.models.geo_zone import GeoZone
from core.models.tile import TILE_DEFAULT_ZOOM, Tile
from core.utils.logs_helpers import log_command_event, log_command_progress

BATCH_SIZE = 100000


def log_event(info: str):
    log_command_event(command_name="create_tile", info=info)


def lon_to_tile_x(lon: float, zoom: int) -> int:
    return math.floor((lon + 180) / 360 * 2**zoom)


def lat_to_tile_y(lat: float, zoom: int) -> int:
    lat_rad = math.radians(lat)
    return math.floor(
        (1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi)
        / 2
        * 2**zoom
    )


class Command(CommandRunTrackerMixin, BaseCommand):
    help = "Populate tile table"

    def add_arguments(self, parser):
        parser.add_argument("--x-min", type=int, required=False)
        parser.add_argument("--x-max", type=int, required=False)
        parser.add_argument("--y-min", type=int, required=False)
        parser.add_argument("--y-max", type=int, required=False)
        parser.add_argument("--z-min", type=int, required=False)
        parser.add_argument("--z-max", type=int, required=False)
        parser.add_argument("--geozone-uuid", type=str, required=False)

    def handle(self, *args, **options):
        geozone_uuid = options.get("geozone_uuid")
        has_bounds = all(
            options.get(k) is not None for k in ("x_min", "x_max", "y_min", "y_max")
        )

        if geozone_uuid and has_bounds:
            raise CommandError(
                "--geozone-uuid cannot be specified together with --x-min, --x-max, --y-min, --y-max"
            )

        if not geozone_uuid and not has_bounds:
            raise CommandError(
                "Either --geozone-uuid or --x-min, --x-max, --y-min, --y-max must be specified"
            )

        z_min = options.get("z_min") or TILE_DEFAULT_ZOOM
        z_max = options.get("z_max") or TILE_DEFAULT_ZOOM

        if geozone_uuid:
            x_min, x_max, y_min, y_max = self.get_bounds_from_geozone(
                geozone_uuid, z_min
            )
        else:
            x_min = options["x_min"]
            x_max = options["x_max"]
            y_min = options["y_min"]
            y_max = options["y_max"]

        if x_min > x_max:
            raise CommandError(
                f"--x-min must be smaller than --x-max, current: --x-min: {x_min}, --x-max: {x_max}"
            )

        if y_min > y_max:
            raise CommandError(
                f"--y-min must be smaller than --y-max, current: --y-min: {y_min}, --y-max: {y_max}"
            )

        if z_min > z_max:
            raise CommandError(
                f"--z-min must be smaller than --z-max, current: --z-min: {z_min}, --z-max: {z_max}"
            )

        self.total = (z_max - z_min + 1) * (y_max - y_min + 1) * (x_max - x_min + 1)
        self.inserted = 0
        self.start_time = time.monotonic()

        log_event(f"Starting insert tiles, total: {self.total}")

        # Insert in pure SQL: generate_series builds the x/y grid and
        # ST_TileEnvelope computes geometry server-side, so the whole batch is
        # one round-trip instead of one per tile.
        row_width = x_max - x_min + 1
        y_band = max(1, BATCH_SIZE // row_width)

        for z in range(z_min, z_max + 1):
            for y_start in range(y_min, y_max + 1, y_band):
                y_end = min(y_start + y_band - 1, y_max)
                self.insert_tiles(z, x_min, x_max, y_start, y_end)

    def get_bounds_from_geozone(self, geozone_uuid: str, zoom: int):
        geozone = (
            GeoZone.objects.annotate(envelope=Envelope("geometry"))
            .values("name", "envelope")
            .filter(uuid=geozone_uuid)
            .first()
        )

        if not geozone:
            raise CommandError(f"GeoZone with uuid {geozone_uuid} not found")

        log_event(f"Using geozone: {geozone['name']}")

        envelope = geozone["envelope"]
        min_lon, min_lat, max_lon, max_lat = envelope.extent

        x_min = lon_to_tile_x(min_lon, zoom)
        x_max = lon_to_tile_x(max_lon, zoom)
        y_min = lat_to_tile_y(max_lat, zoom)
        y_max = lat_to_tile_y(min_lat, zoom)

        return x_min, x_max, y_min, y_max

    def insert_tiles(self, z, x_min, x_max, y_min, y_max):
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {Tile._meta.db_table} (created_at, updated_at, x, y, z, geometry)
                SELECT now(), now(), x, y, %(z)s,
                       ST_Transform(ST_TileEnvelope(%(z)s, x, y), %(srid)s)
                FROM generate_series(%(x_min)s, %(x_max)s) AS x,
                     generate_series(%(y_min)s, %(y_max)s) AS y
                ON CONFLICT (x, y, z) DO NOTHING
                """,
                {
                    "z": z,
                    "srid": SRID,
                    "x_min": x_min,
                    "x_max": x_max,
                    "y_min": y_min,
                    "y_max": y_max,
                },
            )

        self.inserted += (x_max - x_min + 1) * (y_max - y_min + 1)
        log_command_progress("create_tile", self.inserted, self.total, self.start_time)
