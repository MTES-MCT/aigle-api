import time
import re
from typing import Any, Dict, Iterable
from django.core.management.base import BaseCommand
from core.management.base import CommandRunTrackerMixin
from rest_framework import serializers
from django.db import connection
from django.db.models import F, Func, Value
from django.contrib.gis.db.models.aggregates import Union

from rest_framework_gis.serializers import GeometryField
from django.contrib.gis.db.models.functions import Area, Intersection


from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from core.models.geo_epci import GeoEpci
from core.utils.cache import (
    invalidate_tileset_filter_caches,
    invalidate_user_geo_caches,
)
from core.utils.logs_helpers import log_command_event, log_command_progress

PERCENTAGE_COMMUNE_INCLUDED_THRESHOLD = 0.6

# Strict SQL identifier pattern — schema/table names interpolated into raw SQL must match
# this (see get_rows_to_insert_from_table). Mirrors insert_shp / import_custom_zones.
IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class EpciRowSerializer(serializers.Serializer):
    id = serializers.CharField()
    code_siren = serializers.CharField()
    geometry = GeometryField()
    nom = serializers.CharField()


TABLE_COLUMNS = [col for col in EpciRowSerializer().get_fields().keys()]


def log_event(info: str):
    log_command_event(command_name="import_geoepcis", info=info)


class Command(CommandRunTrackerMixin, BaseCommand):
    help = "Import EPCIs from another schema, generated from adminexpress"

    def add_arguments(self, parser):
        parser.add_argument("--table-name", type=str, default="epci")
        parser.add_argument("--table-schema", type=str, default="epci")
        parser.add_argument(
            "--department-code",
            action="append",
            required=False,
            help="INSEE code of a department to restrict the import to (repeatable)",
        )

    def get_rows_to_insert_from_table(
        self, table_name: str, table_schema: str
    ) -> Iterable[Dict[str, Any]]:
        # Schema/table are SQL identifiers and cannot be passed as %s parameters, so they
        # are interpolated into the query string. Validate them against a strict identifier
        # pattern first to prevent SQL injection via the --table-name/--table-schema args.
        if not IDENTIFIER_RE.match(table_schema) or not IDENTIFIER_RE.match(table_name):
            raise ValueError(f"Invalid table identifier: {table_schema}.{table_name}")

        self.cursor = connection.cursor()

        self.cursor.execute("SELECT count(*) FROM %s.%s" % (table_schema, table_name))
        self.total = self.cursor.fetchone()[0]
        self.cursor.execute(
            "SELECT %s FROM %s.%s ORDER BY id"
            % (", ".join(TABLE_COLUMNS), table_schema, table_name)
        )
        return map(lambda row: dict(zip(TABLE_COLUMNS, row)), self.cursor)

    @staticmethod
    def _matches_department_codes(geometry, primary_department, department_codes):
        """True when the EPCI overlaps ANY of the requested departments, not just the
        one it overlaps most."""
        if primary_department.insee_code in department_codes:
            return True

        return GeoDepartment.objects.filter(
            insee_code__in=department_codes, geometry__intersects=geometry
        ).exists()

    def handle(self, *args, **options):
        table_name = options["table_name"]
        table_schema = options["table_schema"]
        department_codes = options.get("department_code") or None

        log_event(f"Starting importing epcis from {table_schema}.{table_name}")
        if department_codes:
            log_event(f"Restricted to departments: {', '.join(department_codes)}")

        rows_to_insert = self.get_rows_to_insert_from_table(
            table_name=table_name,
            table_schema=table_schema,
        )

        start_time = time.monotonic()
        for index, row in enumerate(rows_to_insert):
            log_command_progress("import_geoepcis", index + 1, self.total, start_time)

            serializer = EpciRowSerializer(data=row)
            if not serializer.is_valid():
                log_event(
                    f"Invalid row: {row}, errors: {serializer.errors} skipping..."
                )
                continue

            epci_serialized = serializer.validated_data

            department = (
                GeoDepartment.objects.filter(
                    geometry__intersects=epci_serialized["geometry"]
                )
                .annotate(
                    intersection_area=Area(
                        Intersection("geometry", epci_serialized["geometry"])
                    )
                )
                .order_by("-intersection_area")
                .only("id", "insee_code")
                .first()
            )

            if department is None:
                log_event(
                    f"No department found for epci {epci_serialized['nom']} "
                    f"({epci_serialized['code_siren']}), skipping..."
                )
                continue

            # An EPCI straddling several departments is filed under the one it overlaps
            # most, but a --department-code run must still import it (and link ALL its
            # communes) when ANY of its departments was asked for — otherwise its
            # communes in the other department stay unlinked forever.
            if department_codes and not self._matches_department_codes(
                epci_serialized["geometry"], department, department_codes
            ):
                continue

            member_ids = list(
                GeoCommune.objects.filter(
                    geometry__intersects=epci_serialized["geometry"]
                )
                .annotate(
                    intersection_area=Area(
                        Intersection("geometry", epci_serialized["geometry"])
                    ),
                    total_area=Area("geometry"),
                    # NULLIF: a degenerate zero-area commune geometry would otherwise
                    # abort the whole import with a division by zero.
                    intersection_percentage=F("intersection_area")
                    / Func(F("total_area"), Value(0.0), function="NULLIF"),
                )
                .filter(
                    intersection_percentage__gte=PERCENTAGE_COMMUNE_INCLUDED_THRESHOLD
                )
                .values_list("id", flat=True)
            )

            # The EPCI's geometry is the union of its member communes, NOT the source
            # polygon. Membership is decided by a 60% areal overlap, so the source
            # polygon leaves up to 40% of each member commune outside it — and since a
            # user group scoped to an EPCI derives its accessible geometry from that
            # polygon, those slivers would become invisible on the map and undrawable.
            # Geometry and FK membership must describe the same territory.
            member_union = (
                GeoCommune.objects.filter(id__in=member_ids)
                .aggregate(result=Union("geometry"))
                .get("result")
                if member_ids
                else None
            )

            # Upsert on the natural key so the command can be re-run — it is the only
            # way to refresh commune membership, which is now an authorization boundary.
            epci, _ = GeoEpci.objects.update_or_create(
                siren_code=epci_serialized["code_siren"],
                defaults={
                    "name": epci_serialized["nom"],
                    "geometry": member_union or epci_serialized["geometry"],
                    "department_id": department.id,
                },
            )

            # Detach communes that left this EPCI before (re)attaching the current
            # members: a stale link would keep granting access through it.
            GeoCommune.objects.filter(epci_id=epci.id).exclude(
                id__in=member_ids
            ).update(epci_id=None)
            GeoCommune.objects.filter(id__in=member_ids).update(epci_id=epci.id)

        self.cursor.close()

        invalidate_user_geo_caches()
        # Tile-set visibility now depends on commune-to-EPCI membership (the tile-set
        # repository resolves EPCI zones through GeoCommune.epci), and the tileset-filter
        # cache does NOT fold in the geo version — so a membership change would keep
        # serving the old perimeter until its TTL without this.
        invalidate_tileset_filter_caches()
        log_event("Invalidated user geo and tileset filter caches after EPCI import")
