from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from core.models.geo_commune import GeoCommune
from django.contrib.gis.db import models as models_gis


class ParcelManager(models.Manager):
    def get_queryset(self):
        # by default we defer geometry field as it's heavy to load in memory and not necessary
        # we prefer to handle geometric operations at database level for better performances
        return super().get_queryset().defer("geometry")


class Parcel(TimestampedModelMixin, UuidModelMixin, DeletableModelMixin):
    id_parcellaire = models.CharField(unique=True, max_length=DEFAULT_MAX_LENGTH)

    prefix = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    section = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    num_parcel = models.CharField(max_length=DEFAULT_MAX_LENGTH)

    contenance = models.IntegerField()
    arpente = models.BooleanField()

    geometry = models_gis.GeometryField()

    commune = models.ForeignKey(
        GeoCommune, related_name="parcels", on_delete=models.CASCADE
    )

    refreshed_at = models.DateTimeField()

    objects = ParcelManager()

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + [
            models.Index(fields=["section", "num_parcel", "commune"]),
            models.Index(fields=["num_parcel"]),
            models.Index(fields=["section"]),
        ]
