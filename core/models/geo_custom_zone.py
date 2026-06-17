from common.constants.models import DEFAULT_MAX_LENGTH
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.models.geo_zone import GeoZone
from django.db import models


class GeoCustomZoneStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "ACTIVE"
    INACTIVE = "INACTIVE", "INACTIVE"


class GeoCustomZoneType(models.TextChoices):
    COMMON = "COMMON", "COMMON"
    COLLECTIVITY_MANAGED = "COLLECTIVITY_MANAGED", "COLLECTIVITY_MANAGED"


class GeoCustomZone(GeoZone):
    color = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True, null=True)
    geo_custom_zone_status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=GeoCustomZoneStatus.choices,
        default=GeoCustomZoneStatus.ACTIVE,
    )
    geo_custom_zone_type = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=GeoCustomZoneType.choices,
        default=GeoCustomZoneType.COMMON,
    )
    # custom zones have associated collectivities
    geo_zones = models.ManyToManyField(GeoZone, related_name="geo_custom_zones")
    geo_custom_zone_category = models.ForeignKey(
        GeoCustomZoneCategory,
        related_name="geo_custom_zones",
        on_delete=models.CASCADE,
        null=True,
    )
    name_short = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True, null=True)
    # id of the source row a zone was imported from (e.g. detections.zae_layer.id,
    # which is int8); null for zones created manually through the app. Same role as
    # the import_id on Detection / DetectionObject (see common.models.importable),
    # but BigInteger to match the bigint source column.
    import_id = models.BigIntegerField(null=True)

    class Meta:
        indexes = []
