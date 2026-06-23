from django.db import transaction
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver

from core.models.detection import Detection
from core.models.detection_data import DetectionData
from core.models.detection_object import DetectionObject
from core.models.parcel import Parcel
from core.models.tile_set import TileSet
from core.models.user_group import UserGroup, UserUserGroup
from core.utils.cache import (
    count_cache_invalidation_suppressed,
    invalidate_caches_for_user,
    invalidate_caches_for_group,
    invalidate_count_caches,
    invalidate_tileset_filter_caches,
)

# Invalidation is deferred to transaction.on_commit so a concurrent reader cannot
# repopulate the cache with not-yet-committed data under the freshly bumped
# version. If the transaction rolls back, the bump never fires. Outside an atomic
# block, on_commit runs the callback immediately.


@receiver(post_save, sender=UserUserGroup)
@receiver(post_delete, sender=UserUserGroup)
def on_user_group_membership_change(sender, instance, **kwargs):  # noqa: ARG001
    user_id = instance.user_id
    transaction.on_commit(lambda: invalidate_caches_for_user(user_id))


@receiver(m2m_changed, sender=UserGroup.geo_zones.through)
def on_user_group_geo_zones_change(sender, instance, action, **kwargs):  # noqa: ARG001
    if action in ("post_add", "post_remove", "post_clear"):
        group_id = instance.id
        transaction.on_commit(lambda: invalidate_caches_for_group(group_id))


@receiver(post_save, sender=TileSet)
@receiver(post_delete, sender=TileSet)
def on_tileset_change(sender, **kwargs):  # noqa: ARG001
    transaction.on_commit(invalidate_tileset_filter_caches)


@receiver(m2m_changed, sender=TileSet.geo_zones.through)
def on_tileset_geo_zones_change(sender, action, **kwargs):  # noqa: ARG001
    if action in ("post_add", "post_remove", "post_clear"):
        transaction.on_commit(invalidate_tileset_filter_caches)


# --- Geo zone geometry changes ---
# Geo zones (regions, departments, communes, EPCIs) are only ever written by the
# bulk import commands, which use per-row save() in autocommit. A model signal here
# would fire tens of thousands of times per import for no benefit, so invalidation
# is done once at the end of each geo import command (each calls
# invalidate_user_geo_caches() directly). The USER_GEO_CACHE_TTL covers other edits.


# --- Detection / parcel single-row writes → invalidate pagination count caches ---
# Fires for interactive single edits/creates (which use save()). Bulk paths
# (bulk_create/bulk_update) bypass post_save, so import_detections and the bulk
# update service invalidate counts explicitly instead.


def _on_count_relevant_change(sender, **kwargs):  # noqa: ARG001
    if count_cache_invalidation_suppressed():
        return
    transaction.on_commit(invalidate_count_caches)


for _count_model in (Detection, DetectionData, DetectionObject, Parcel):
    post_save.connect(_on_count_relevant_change, sender=_count_model)
    post_delete.connect(_on_count_relevant_change, sender=_count_model)


# DetectionObject.geo_custom_zones is a count filter dimension (customZonesUuids),
# so changing the association must invalidate counts. Raw-SQL associations (e.g.
# import_detections.associate_detections_to_custom_zones) bypass this signal and
# invalidate explicitly instead.
@receiver(m2m_changed, sender=DetectionObject.geo_custom_zones.through)
def on_detection_object_custom_zones_change(sender, action, **kwargs):  # noqa: ARG001
    if action in ("post_add", "post_remove", "post_clear") and (
        not count_cache_invalidation_suppressed()
    ):
        transaction.on_commit(invalidate_count_caches)
