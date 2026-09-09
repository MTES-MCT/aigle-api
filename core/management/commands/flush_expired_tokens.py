from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.management.base import CommandRunTrackerMixin
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="flush_expired_tokens", info=info)


class Command(CommandRunTrackerMixin, BaseCommand):
    """Purge les refresh tokens expirés de la liste noire simplejwt.

    ROTATE_REFRESH_TOKENS écrit une ligne OutstandingToken à chaque rafraîchissement,
    soit environ une par utilisateur et par heure : sans purge la table croît sans fin.
    Simple délégation à la commande `flushexpiredtokens` de simplejwt, qui n'apparaît pas
    dans l'admin run-command (elle ne liste que les commandes de l'app `core`).
    """

    help = "Purge les refresh tokens expirés de la liste noire (simplejwt)"

    def handle(self, *args, **options):
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        before = OutstandingToken.objects.count()
        call_command("flushexpiredtokens")
        after = OutstandingToken.objects.count()

        log_event(f"Jetons expirés purgés: {before - after} (restants: {after})")
