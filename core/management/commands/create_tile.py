import math

from django.contrib.gis.db.models.functions import Envelope
from django.core.management.base import BaseCommand, CommandError

from core.models.geo_zone import GeoZone
from core.models.tile import TILE_DEFAULT_ZOOM, Tile
from core.utils.logs_helpers import log_command_event

BATCH_SIZE = 10000


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


class Command(BaseCommand):
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

        self.tiles = []
        self.total = (z_max - z_min + 1) * (y_max - y_min + 1) * (x_max - x_min + 1)
        self.inserted = 0

        log_event(f"Starting insert tiles, total: {self.total}")

        for z in range(z_min, z_max + 1):
            for y in range(y_min, y_max + 1):
                for x in range(x_min, x_max + 1):
                    tile = Tile(x=x, y=y, z=z)
                    self.tiles.append(tile)

                    if len(self.tiles) == BATCH_SIZE:
                        self.insert_tiles()

        self.insert_tiles()

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

    def insert_tiles(self):
        if not len(self.tiles):
            return

        Tile.objects.bulk_create(self.tiles, ignore_conflicts=True)
        self.inserted += len(self.tiles)
        self.tiles = []
        log_event(f"Inserting tiles: {self.inserted}/{self.total}")
