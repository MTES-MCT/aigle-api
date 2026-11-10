from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from core.management.base import CommandRunTrackerMixin
from core.models.analytic_log import AnalyticLog, AnalyticLogType
from core.models.user import User, UserRole
from core.utils.logs_helpers import log_command_event

DEFAULT_INACTIVITY_DAYS = 365
HISTORY_CHANGE_REASON = "INACTIVITY"


def log_event(info: str):
    log_command_event(command_name="deactivate_inactive_users", info=info)


class Command(CommandRunTrackerMixin, BaseCommand):
    """Désactive (rôle DEACTIVATED) les comptes sans connexion depuis `--days` jours.

    `last_login` ne suffit pas : il n'est mis à jour qu'à l'obtention d'un JWT, et la
    rotation des refresh tokens garde un utilisateur assidu connecté sans jamais repasser
    par le login. La connexion retenue est donc aussi le log USER_ACCESS, écrit à chaque
    chargement de l'app. Un compte créé dans la période n'est pas touché, et les
    SUPER_ADMIN sont exclus pour ne pas verrouiller l'équipe plateforme.
    """

    help = (
        "Désactive les utilisateurs sans connexion depuis --days jours "
        f"({DEFAULT_INACTIVITY_DAYS} par défaut, SUPER_ADMIN exclus)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_INACTIVITY_DAYS,
            help="Durée sans connexion, en jours, au-delà de laquelle désactiver",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste les comptes concernés sans les désactiver",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]

        if days < 1:
            raise CommandError("--days doit être supérieur ou égal à 1")

        cutoff = timezone.now() - timedelta(days=days)
        users = list(get_inactive_users(cutoff))

        prefix = "[dry-run] " if dry_run else ""
        for user in users:
            log_event(
                f"{prefix}{user.email} ({user.user_role}), "
                f"dernier login: {user.last_login or 'jamais'}"
            )

        if not dry_run:
            deactivate_users(users)

        log_event(
            f"{prefix}{len(users)} utilisateur(s) sans connexion depuis le "
            f"{cutoff:%Y-%m-%d} {'à désactiver' if dry_run else 'désactivé(s)'}"
        )


def get_inactive_users(cutoff):
    recent_access = AnalyticLog.objects.filter(
        user=OuterRef("pk"),
        analytic_log_type=AnalyticLogType.USER_ACCESS,
        created_at__gte=cutoff,
    )

    return (
        User.objects.filter(deleted=False, created_at__lt=cutoff)
        .exclude(user_role__in=[UserRole.DEACTIVATED, UserRole.SUPER_ADMIN])
        .filter(Q(last_login__isnull=True) | Q(last_login__lt=cutoff))
        .exclude(Exists(recent_access))
        .order_by("email")
    )


@transaction.atomic
def deactivate_users(users):
    # One save() per user (not a bulk update) so each change gets its history row.
    for user in users:
        user.user_role = UserRole.DEACTIVATED
        user._change_reason = HISTORY_CHANGE_REASON
        user.save(update_fields=["user_role", "updated_at"])
