from django.db import models


from common.models.timestamped import TimestampedModelMixin
from django.contrib.gis.db import models as models_gis
from django.core.validators import MinValueValidator
from django.contrib.gis.geos import GEOSGeometry

from core.utils.postgis import ST_TileEnvelope

TILE_DEFAULT_ZOOM = 19


class TileManager(models_gis.Manager):
    def bulk_create(self, objs, **kwargs):
        for obj in objs:
            obj.geometry = GEOSGeometry(ST_TileEnvelope(z=obj.z, x=obj.x, y=obj.y))

        super().bulk_create(objs, **kwargs)


class Tile(TimestampedModelMixin):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["x", "y", "z"], name="xyz_unique"),
        ]

    objects = TileManager()

    x = models.IntegerField(validators=[MinValueValidator(0)])
    y = models.IntegerField(validators=[MinValueValidator(0)])
    z = models.IntegerField(
        default=TILE_DEFAULT_ZOOM, validators=[MinValueValidator(0)]
    )

    geometry = models_gis.GeometryField()

    def save(self, *args, **kwargs):
        self.geometry = GEOSGeometry(ST_TileEnvelope(z=self.z, x=self.x, y=self.y))
        super(Tile, self).save(*args, **kwargs)
