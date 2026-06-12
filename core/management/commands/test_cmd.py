from time import sleep

from django.core.management.base import BaseCommand, CommandError

from core.models.user import User
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="test_cmd", info=info)


class Command(BaseCommand):
    help = "No-op command used to verify the admin run-command flow end-to-end."

    def add_arguments(self, parser):
        parser.add_argument("--sleep-seconds", type=int, required=False, default=5)
        parser.add_argument("--fail", action="store_true", required=False)
        parser.add_argument("--crash", action="store_true", required=False)
        parser.add_argument("--note", type=str, required=False)

    def handle(self, *args, **options):
        sleep_seconds = options["sleep_seconds"]
        should_fail = options["fail"]
        should_crash = options["crash"]
        note = options["note"]

        log_event("started")
        log_event(
            f"options: sleep_seconds={sleep_seconds}, fail={should_fail}, crash={should_crash}, note={note!r}"
        )

        user_count = User.objects.count()
        log_event(f"db reachable: {user_count} users")

        log_event(f"sleeping for {sleep_seconds}s")
        sleep(sleep_seconds)
        log_event("woke up")

        if should_fail:
            raise CommandError("test_cmd failed on purpose (--fail was set)")
        if should_crash:
            raise RuntimeError("test_cmd crashed on purpose (--crash was set)")

        log_event("done")
