from django.core.management.base import BaseCommand
from django.contrib.gis.geos import GEOSGeometry
from django.db import connection
from django.contrib.gis.db.models.functions import Intersection

import uuid
import json
import shapefile

BATCH_SIZE = 10000


class Command(BaseCommand):
    help = "Convert a shape to postgis geometry and insert it in database"

    def add_arguments(self, parser):
        parser.add_argument("--shp-path", type=str, required=True)
        parser.add_argument("--table-schema", type=str, default="temp")
        parser.add_argument("--table-name", type=str, default="zones")
        parser.add_argument("--name", type=str)

    def handle(self, *args, **options):
        name = options.get("name") or uuid.uuid4()
        shape = shapefile.Reader(options["shp_path"])

        geometries = []

        for feature in shape.shapeRecords():
            geometries.append(
                GEOSGeometry(json.dumps(feature.__geo_interface__["geometry"]))
            )

        cursor = connection.cursor()

        if len(geometries) == 1:
            geometry_to_insert = geometries[0]
        else:
            geometry_to_insert = Intersection(*geometries)

        geometry_to_insert.transform(2154, 4326)
        cursor.execute(
            f"""
            INSERT INTO {options["table_schema"]}.{options["table_name"]} (name, geometry)
            VALUES  
                ('{name}', '{geometry_to_insert}')
        """
        )
