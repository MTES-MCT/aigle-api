from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from core.management.base import CommandRunTrackerMixin
from rest_framework_api_key.models import APIKey

from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="create_api_key", info=info)


class Command(CommandRunTrackerMixin, BaseCommand):
    help = "Create an API key for external API access"

    def add_arguments(self, parser):
        parser.add_argument(
            "--name", type=str, required=True, help="Name to identify this API key"
        )
        parser.add_argument(
            "--expiry-days",
            type=int,
            required=False,
            help="Number of days until expiry (optional)",
        )

    def _reveal_key(self, key: str):
        """La clé en clair ne doit jamais atterrir dans ``CommandRun.output`` : cette
        colonne est persistée, rendue par l'admin run-command et recopiée entre
        environnements (aigle-utils/import_from_preprod.sql). Une clé d'API ouvre
        /api/external/* sans authentification utilisateur.

        Sur un lancement CLI, seul le logger ``aigle`` est capturé : stdout va au
        terminal de l'opérateur et nulle part ailleurs. Sur un lancement API (Celery),
        stdout EST capturé, donc on ne révèle rien et l'opérateur relance en CLI."""
        if getattr(self, "_aigle_cli_invocation", False):
            self.stdout.write(f"API Key: {key}")
            return

        log_event(
            "Clé générée mais non affichée : relancer la commande en CLI "
            "(python manage.py create_api_key) pour la récupérer, puis révoquer "
            "celle-ci avec revoke_api_key."
        )

    def handle(self, *args, **options):
        name = options["name"]
        expiry_days = options.get("expiry_days")

        if expiry_days:
            expiry_date = datetime.now() + timedelta(days=expiry_days)
            api_key, key = APIKey.objects.create_key(name=name, expiry_date=expiry_date)
            expiry_str = expiry_date.strftime("%Y-%m-%d %H:%M:%S")

            log_event(
                f"API Key created successfully - Name: {name}, Expires: {expiry_str}, "
                f"Prefix: {api_key.prefix}"
            )
        else:
            api_key, key = APIKey.objects.create_key(name=name)

            log_event(
                f"API Key created successfully - Name: {name}, Expires: Never, "
                f"Prefix: {api_key.prefix}"
            )

        self._reveal_key(key)
