from django.core.management.base import BaseCommand, CommandError

from core.models.tile import TILE_DEFAULT_ZOOM, Tile

BATCH_SIZE = 10000


class Command(BaseCommand):
    help = "Populate tile table"

    def add_arguments(self, parser):
        parser.add_argument("--x-min", type=int, required=True)
        parser.add_argument("--x-max", type=int, required=True)
        parser.add_argument("--y-min", type=int, required=True)
        parser.add_argument("--y-max", type=int, required=True)
        parser.add_argument("--z-min", type=int, required=False)
        parser.add_argument("--z-max", type=int, required=False)

    def handle(self, *args, **options):
        x_min = options["x_min"]
        x_max = options["x_max"]
        y_min = options["y_min"]
        y_max = options["y_max"]
        z_min = options.get("z_min") or TILE_DEFAULT_ZOOM
        z_max = options.get("z_max") or TILE_DEFAULT_ZOOM

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

        print(f"Starting insert tiles, total: {self.total}")

        for z in range(z_min, z_max + 1):
            for y in range(y_min, y_max + 1):
                for x in range(x_min, x_max + 1):
                    tile = Tile(x=x, y=y, z=z)
                    self.tiles.append(tile)

                    if len(self.tiles) == BATCH_SIZE:
                        self.insert_tiles()

        self.insert_tiles()

    def insert_tiles(self):
        if not len(self.tiles):
            return

        Tile.objects.bulk_create(self.tiles, ignore_conflicts=True)
        self.inserted += len(self.tiles)
        self.tiles = []
        print(f"Inserting tiles: {self.inserted}/{self.total}")
