from django.core.management.base import BaseCommand, CommandError

from core.management.base import CommandRunTrackerMixin
from core.models.detection_type_overlap_report import DetectionTypeOverlapReport
from core.models.geo_zone import GeoZone
from core.services.detection_type_overlap import (
    DetectionTypeOverlapCounts,
    DetectionTypeOverlapService,
)
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="compute_detection_type_overlaps", info=info)


def format_rate(scope: str, label: str, problematic: int, total: int) -> str:
    rate = f"{problematic / total * 100:.2f} %" if total else "n/a"
    return (
        f"{scope} | {label}: {problematic} problematic, "
        f"{total - problematic} without issue, rate {rate}"
    )


class Command(CommandRunTrackerMixin, BaseCommand):
    help = (
        "Rate of detections of the latest year of a zone that overlap a detection "
        "of another object type, overall, one of the two being prescribable, and per "
        "prescribable object type (all detections, in zones à enjeux, outside them). "
        "Saved as the zone's report, replacing the previous one"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--geozone-uuid",
            type=str,
            required=True,
            help="Zone (department, commune...) whose linked tile sets are analysed",
        )

    def handle(self, *args, **options):
        geo_zone = GeoZone.objects.filter(uuid=options["geozone_uuid"]).first()
        if not geo_zone:
            raise CommandError(f"Geozone {options['geozone_uuid']} not found")

        indicator = DetectionTypeOverlapService.compute_indicator(geo_zone=geo_zone)
        # Not an error: it is queued after every import, a zae one included, which can
        # come before the zone has any detection.
        if not indicator.tile_sets:
            DetectionTypeOverlapReport.objects.filter(geo_zone=geo_zone).delete()
            log_event(
                f"No active background tile set linked to {geo_zone.name}: no report"
            )
            return

        log_event(
            f"{geo_zone.name} ({geo_zone.geo_zone_type}), latest tile sets: "
            + ", ".join(
                f"{tile_set.name} ({tile_set.date.isoformat()})"
                for tile_set in indicator.tile_sets
            )
        )
        log_event(
            "Prescribable object types: "
            + (
                ", ".join(
                    f"{object_type.name} ({object_type.prescription_duration_years} years)"
                    for object_type in indicator.prescribable_object_types
                )
                or "none"
            )
        )

        scopes = [
            ("All", indicator.all),
            ("In zones à enjeux", indicator.in_custom_zones),
            ("Outside zones à enjeux", indicator.outside_custom_zones),
        ]
        for scope, counts in scopes:
            self.log_scope(scope, counts, indicator.prescribable_object_types)

        DetectionTypeOverlapService.save_report(geo_zone=geo_zone, indicator=indicator)
        log_event(f"Report saved for {geo_zone.name}")

    @staticmethod
    def log_scope(scope: str, counts: DetectionTypeOverlapCounts, object_types):
        log_event(f"{scope} | {counts.total} detections")
        log_event(
            format_rate(
                scope, "overlapping another type", counts.overlapping, counts.total
            )
        )
        log_event(
            format_rate(
                scope,
                "overlapping another type, one being prescribable",
                counts.overlapping_prescribable,
                counts.total,
            )
        )
        for object_type in object_types:
            log_event(
                format_rate(
                    scope,
                    f"overlapping another type, one being {object_type.name}",
                    counts.overlapping_by_object_type[object_type.id],
                    counts.total,
                )
            )
