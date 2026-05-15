from django.core.management.base import BaseCommand
from django.contrib.gis.geos import GEOSGeometry
from django.db import connection
from django.contrib.gis.db.models.functions import Intersection

import re
import uuid
import json
import shapefile

from core.constants.geo import SRID

BATCH_SIZE = 10000

IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class Command(BaseCommand):
    help = "Convert a shape to postgis geometry and insert it in database"

    def add_arguments(self, parser):
        parser.add_argument("--shp-path", type=str, required=True)
        parser.add_argument("--table-schema", type=str, default="temp")
        parser.add_argument("--table-name", type=str, default="zones")
        parser.add_argument("--name", type=str)

    def handle(self, *args, **options):
        name = options.get("name") or str(uuid.uuid4())

        table_schema = options["table_schema"]
        table_name = options["table_name"]

        if not IDENTIFIER_RE.match(table_schema):
            raise ValueError(f"Invalid table schema: {table_schema}")
        if not IDENTIFIER_RE.match(table_name):
            raise ValueError(f"Invalid table name: {table_name}")

        shape = shapefile.Reader(options["shp_path"])

        geometries = []

        for feature in shape.shapeRecords():
            geometries.append(
                GEOSGeometry(
                    json.dumps(feature.__geo_interface__["geometry"]), srid=SRID
                )
            )

        if len(geometries) == 1:
            geometry_to_insert = geometries[0]
        else:
            geometry_to_insert = Intersection(*geometries)

        cursor = connection.cursor()
        cursor.execute(
            f"INSERT INTO {table_schema}.{table_name} (name, geometry) VALUES (%s, %s)",
            [name, geometry_to_insert.wkt],
        )
