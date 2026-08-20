from common.constants.models import DEFAULT_MAX_LENGTH
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.models.geo_zone import GeoZone, GeoZoneManager
from django.db import models


class GeoCustomZoneStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "ACTIVE"
    INACTIVE = "INACTIVE", "INACTIVE"


class GeoCustomZoneQuerySet(models.QuerySet):
    def active(self):
        """Only zones à enjeux that are turned on.

        The default idiom for ANY user-facing read of custom zones: a deactivated zone
        must not surface for regular users. Available on `GeoCustomZone.objects` and,
        because the M2M related managers subclass this manager, on relations too, e.g.
        `detection_object.geo_custom_zones.active()`. Admin/management code that must also
        see deactivated zones (CRUD, import upsert, reactivation) keeps plain `objects`.
        """
        return self.filter(geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE)


# Keeps GeoZoneManager's geometry deferral while adding `active()`. `objects` stays
# unfiltered on purpose (a filtered default manager would hide deactivated zones from the
# admin/import/base-manager paths that need them); `active()` is the explicit opt-in.
GeoCustomZoneManager = GeoZoneManager.from_queryset(GeoCustomZoneQuerySet)


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
    description = models.TextField(null=True, blank=True)
    # id of the source row a zone was imported from (e.g. detections.zae_layer.id,
    # which is int8); null for zones created manually through the app. Same role as
    # the import_id on Detection / DetectionObject (see common.models.importable),
    # but BigInteger to match the bigint source column.
    import_id = models.BigIntegerField(null=True)
    # original detections.zae_layer.layer_name at import time; null for zones created
    # manually. Unlike `name` (admin-editable), this is a stable key for matching a
    # zone back to its source zae layer. editable=False keeps it out of forms/serializers.
    import_layer_name = models.CharField(
        max_length=DEFAULT_MAX_LENGTH, null=True, editable=False
    )

    objects = GeoCustomZoneManager()

    class Meta:
        indexes = []
