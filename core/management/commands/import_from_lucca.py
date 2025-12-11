from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Literal, TypedDict, get_type_hints
import mysql.connector
from django.core.management.base import BaseCommand, CommandError

from core.utils.logs_helpers import log_command_event

LuccaAnalyticsTable = Literal["stats_history", "stats_logs", "stats_users"]
LuccaAnalyticsColumnType = Literal["int", "datetime", "str"]


@dataclass
class LuccaAnalyticsColumn:
    name: str
    type: LuccaAnalyticsColumnType


class LuccaStatHistory(TypedDict):
    id: int
    dossier_id: int
    adherent_id: int
    action_date: datetime
    action_type: str
    ville: str
    interco: str
    departement: str


class LuccaStatLog(TypedDict):
    id: int
    utilisateur_id: int
    connexion_date: datetime


class LuccaStatUser(TypedDict):
    id: int
    adherent_id: str
    departement: str
    appartenance: str
    nom_appartenance: str
    niveau_acces: str
    utilisateur_id: str


LUCCA_ANALYTICS_TABLE_COLUMNS_MAP: Dict[
    LuccaAnalyticsTable, List[LuccaAnalyticsColumn]
] = {
    "stats_history": [
        LuccaAnalyticsColumn(field, field_type.__name__)
        for field, field_type in get_type_hints(LuccaStatHistory).items()
    ],
    "stats_logs": [
        LuccaAnalyticsColumn(field, field_type.__name__)
        for field, field_type in get_type_hints(LuccaStatLog).items()
    ],
    "stats_users": [
        LuccaAnalyticsColumn(field, field_type.__name__)
        for field, field_type in get_type_hints(LuccaStatUser).items()
    ],
}


def log_event(info: str):
    log_command_event(command_name="import_from_lucca", info=info)


class Command(BaseCommand):
    help = "Import data from Lucca analytics database"

    def __init__(self):
        self.connection = None
        self.cursor = None

    def add_arguments(self, parser):
        parser.add_argument(
            "--db-host",
            type=str,
            help="Database host address",
            default="lucca-analy-5318.mysql.c.osc-fr1.scalingo-dbs.com",
        )
        parser.add_argument(
            "--db-name", type=str, help="Database name", default="stats"
        )
        parser.add_argument(
            "--db-user", type=str, help="Database user", default="lucca_analy_5318"
        )
        parser.add_argument(
            "--db-port", type=int, default=36355, help="Database port (default: 36355)"
        )
        parser.add_argument(
            "--db-password", type=str, required=True, help="Database password"
        )

    def handle(self, *args, **options):
        db_host = options["db_host"]
        db_name = options["db_name"]
        db_user = options["db_user"]
        db_password = options["db_password"]
        db_port = options["db_port"]

        try:
            # Establish SSL connection to remote MySQL database
            log_event(
                f"Connecting to MySQL database {db_name} at {db_host}:{db_port} with SSL..."
            )
            self.connection = mysql.connector.connect(
                host=db_host,
                database=db_name,
                user=db_user,
                password=db_password,
                port=db_port,
                ssl_disabled=False,
                ssl_verify_cert=False,
            )
            self.cursor = self.connection.cursor()
            log_event("Database connection established successfully")

            # Example: Run a test query
            self.cursor.execute("SELECT VERSION();")

            db_version = self.cursor.fetchone()
            if db_version:
                log_event("Successfuly connected to the db")

            import pdb

            pdb.set_trace()
            log_event("Import completed successfully")

        except mysql.connector.Error as e:
            log_event(f"Database error: {e}")
            raise CommandError(f"Database connection failed: {e}")

        except Exception as e:
            log_event(f"Unexpected error: {e}")
            raise CommandError(f"Import failed: {e}")

        finally:
            if self.cursor:
                self.cursor.close()
            if self.connection:
                self.connection.close()
                log_event("Database connection closed")

    # def get_rows(
    #     self, table_name: str,
    # ) -> Iterable[Dict[str, Any]]:
    #     self.cursor = connection.cursor()
    #     self.cursor.execute(
    #         "SELECT count(*) FROM %s.%s WHERE batch_id = %s"
    #         % (table_schema, table_name, f"'{batch_id}'")
    #     )
    #     self.total = self.cursor.fetchone()[0]

    #     table_columns = TABLE_COLUMNS

    #     if with_dates:
    #         table_columns += TABLE_COLUMNS_DATE

    #     self.cursor.execute(
    #         "SELECT %s FROM %s.%s WHERE batch_id = %s ORDER BY score DESC"
    #         % (", ".join(table_columns), table_schema, table_name, f"'{batch_id}'")
    #     )
    #     return map(lambda row: dict(zip(table_columns, row)), self.cursor)
