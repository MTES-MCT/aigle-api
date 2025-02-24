from django.db import connection
from django.db.models import Func, CharField, TextChoices

from django.contrib.gis.db import models as models_gis

from core.contants.geo import SRID


def ST_TileEnvelope(z: int, x: int, y: int):
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT 
                ST_AsText(
                    ST_Transform(
                       ST_TileEnvelope(%s, %s, %s), 
                       {SRID}
                    )
                )
        """,
            [z, x, y],
        )
        row = cursor.fetchone()
        return row[0] if row else None


class Simplify(Func):
    function = "ST_Simplify"
    output_field = models_gis.GeometryField()


class SimplifyPreserveTopology(Func):
    function = "ST_SimplifyPreserveTopology"
    output_field = models_gis.GeometryField()


class SimplifyVW(Func):
    function = "ST_SimplifyVW"
    output_field = models_gis.GeometryField()


class GeometryType(TextChoices):
    POINT = "POINT"
    LINESTRING = "LINESTRING"
    POLYGON = "POLYGON"
    MULTIPOINT = "MULTIPOINT"
    MULTILINESTRING = "MULTILINESTRING"
    MULTIPOLYGON = "MULTIPOLYGON"
    GEOMETRYCOLLECTION = "GEOMETRYCOLLECTION"
    CIRCULARSTRING = "CIRCULARSTRING"
    COMPOUNDCURVE = "COMPOUNDCURVE"
    CURVEPOLYGON = "CURVEPOLYGON"
    MULTICURVE = "MULTICURVE"
    MULTISURFACE = "MULTISURFACE"
    POLYHEDRALSURFACE = "POLYHEDRALSURFACE"
    TRIANGLE = "TRIANGLE"
    TIN = "TIN"


class GetGeometryType(Func):
    function = "GeometryType"
    output_field = CharField(
        choices=GeometryType.choices,
    )
