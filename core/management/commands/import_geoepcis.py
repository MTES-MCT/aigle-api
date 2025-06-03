from typing import Any, Dict, Iterable
from django.core.management.base import BaseCommand
from rest_framework import serializers
from django.db import connection
from django.db.models import F

from rest_framework_gis.serializers import GeometryField
from django.contrib.gis.db.models.functions import Area, Intersection


from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from core.models.geo_epci import GeoEpci
from core.utils.logs_helpers import log_command_event

PERCENTAGE_COMMUNE_INCLUDED_THRESHOLD = 0.6


class EpciRowSerializer(serializers.Serializer):
    id = serializers.CharField()
    code_siren = serializers.CharField()
    geometry = GeometryField()
    nom = serializers.CharField()


TABLE_COLUMNS = [col for col in EpciRowSerializer().get_fields().keys()]


def log_event(info: str):
    log_command_event(command_name="import_geoepcis", info=info)


class Command(BaseCommand):
    help = "Import EPCIs from another schema, generated from adminexpress"

    def add_arguments(self, parser):
        parser.add_argument("--table-name", type=str, default="epci")
        parser.add_argument("--table-schema", type=str, default="epci")

    def get_rows_to_insert_from_table(
        self, table_name: str, table_schema: str
    ) -> Iterable[Dict[str, Any]]:
        self.cursor = connection.cursor()

        self.cursor.execute("SELECT count(*) FROM %s.%s" % (table_schema, table_name))
        self.total = self.cursor.fetchone()[0]
        self.cursor.execute(
            "SELECT %s FROM %s.%s ORDER BY id"
            % (", ".join(TABLE_COLUMNS), table_schema, table_name)
        )
        return map(lambda row: dict(zip(TABLE_COLUMNS, row)), self.cursor)

    def handle(self, *args, **options):
        table_name = options["table_name"]
        table_schema = options["table_schema"]

        log_event(f"Starting importing epcis from {table_schema}.{table_name}")

        rows_to_insert = self.get_rows_to_insert_from_table(
            table_name=table_name,
            table_schema=table_schema,
        )

        for index, row in enumerate(rows_to_insert):
            serializer = EpciRowSerializer(data=row)
            if not serializer.is_valid():
                log_event(
                    f"Invalid row: {row}, errors: {serializer.errors} skipping..."
                )

            epci_serialized = serializer.validated_data

            # get the department that have the biggest surface in common with epci
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
                .only("id")
                .first()
            )

            epci = GeoEpci(
                name=epci_serialized["nom"],
                siren_code=epci_serialized["code_siren"],
                geometry=epci_serialized["geometry"],
                department_id=department.id,
            )
            epci.save()
            communes = (
                GeoCommune.objects.filter(
                    geometry__intersects=epci_serialized["geometry"]
                )
                .annotate(
                    intersection_area=Area(
                        Intersection("geometry", epci_serialized["geometry"])
                    ),
                    total_area=Area("geometry"),
                    intersection_percentage=F("intersection_area") / F("total_area"),
                )
                .filter(
                    intersection_percentage__gte=PERCENTAGE_COMMUNE_INCLUDED_THRESHOLD
                )
            )
            for commune in communes:
                commune.epci_id = epci.id

            GeoCommune.objects.bulk_update(communes, ["epci_id"])

            log_event(f"EPCIs inserted: {index+1}/{self.total}")

        self.cursor.close()
