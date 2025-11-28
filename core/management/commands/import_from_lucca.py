import mysql.connector
from django.core.management.base import BaseCommand, CommandError

from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="import_from_lucca", info=info)


class Command(BaseCommand):
    help = "Import data from Lucca analytics database"

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

        connection = None
        cursor = None

        try:
            # Establish SSL connection to remote MySQL database
            log_event(
                f"Connecting to MySQL database {db_name} at {db_host}:{db_port} with SSL..."
            )
            connection = mysql.connector.connect(
                host=db_host,
                database=db_name,
                user=db_user,
                password=db_password,
                port=db_port,
                ssl_disabled=False,
                ssl_verify_cert=False,
            )
            cursor = connection.cursor()
            log_event("Database connection established successfully")

            # Example: Run a test query
            cursor.execute("SELECT VERSION();")
            db_version = cursor.fetchone()
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
            # Clean up database connections
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                log_event("Database connection closed")
