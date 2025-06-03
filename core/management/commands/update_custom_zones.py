from django.core.management.base import BaseCommand

from core.models.detection import Detection
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_sub_custom_zone import GeoSubCustomZone
from core.models.tile_set import TileSet, TileSetStatus, TileSetType
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="update_custom_zones", info=info)


class Command(BaseCommand):
    help = "Refresh data after update geometry of a custom zone"

    def add_arguments(self, parser):
        parser.add_argument("--zones-uuids", action="append", required=False)
        parser.add_argument("--batch-uuids", action="append", required=False)
        parser.add_argument("--tile-set-uuids", action="append", required=False)

    def handle(self, *args, **options):
        zones_uuids = options["zones_uuids"]
        batch_uuids = options["batch_uuids"]
        tile_set_uuids = options["tile_set_uuids"]

        custom_zones_queryset = GeoCustomZone.objects

        if zones_uuids:
            custom_zones_queryset = custom_zones_queryset.filter(uuid__in=zones_uuids)

        custom_zones = (
            custom_zones_queryset.filter(geometry__isnull=False)
            .prefetch_related("sub_custom_zones")
            .defer("geometry", "sub_custom_zones__geometry")
            .all()
        )

        log_event(
            f"Starting updating detection data for zones: {", ".join([zone.name for zone in custom_zones])}"
        )

        if not batch_uuids:
            batch_uuids_queryset = (
                Detection.objects.exclude(batch_id=None)
                .values_list("batch_id", flat=True)
                .distinct()
            )
            batch_uuids = list(batch_uuids_queryset)

        if not tile_set_uuids:
            tile_set_uuids_queryset = TileSet.objects.exclude(
                tile_set_type=TileSetType.INDICATIVE,
                tile_set_status=TileSetStatus.DEACTIVATED,
            ).values_list("uuid", flat=True)
            tile_set_uuids = list(tile_set_uuids_queryset)

        for zone in custom_zones:
            log_event(f"Updating detection data for zone: {zone.name}")

            GeoCustomZone.objects.raw(
                """
                    insert into core_detectionobject_geo_custom_zones(
                            detectionobject_id,
                            geocustomzone_id
                        )
                    select
                        distinct
                        dobj.id as detectionobject_id,
                        %s as geocustomzone_id
                    from
                        core_detectionobject dobj
                    join core_detection detec on
                        detec.detection_object_id = dobj.id
                    WHERE
                        detec.batch_id = ANY(%s) and
                        detec.tile_set_id = ANY(%s) and
                        ST_Intersects(
                            detec.geometry,
                            (
                                select
                                    geozone.geometry
                                from
                                    core_geozone geozone
                                where
                                    id = %s
                            )
                        )
                    on conflict do nothing;
            """,
                [zone.id, batch_uuids, tile_set_uuids, zone.id],
            )

        sub_custom_zones = [
            sub_custom_zone
            for zone in custom_zones
            for sub_custom_zone in zone.sub_custom_zones
        ]

        for zone in sub_custom_zones:
            log_event(f"Updating detection data for sub-zone: {zone.name}")

            GeoSubCustomZone.objects.raw(
                """
                    insert into core_detectionobject_geo_sub_custom_zones(
                            detectionobject_id,
                            geosubcustomzone_id
                        )
                    select
                        distinct
                        dobj.id as detectionobject_id,
                        %s as geosubcustomzone_id
                    from
                        core_detectionobject dobj
                    join core_detection detec on
                        detec.detection_object_id = dobj.id
                    WHERE
                        detec.batch_id = ANY(%s) and
                        detec.tile_set_id = ANY(%s) and
                        ST_Intersects(
                            detec.geometry,
                            (
                                select
                                    geosubcustomzone.geometry
                                from
                                    core_geosubcustomzone geosubcustomzone
                                where
                                    id = %s
                            )
                        )
                    on conflict do nothing;
            """,
                [zone.id, batch_uuids, tile_set_uuids, zone.id],
            )
