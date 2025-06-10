from django.core.management.base import BaseCommand

from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="test_cmd", info=info)


class Command(BaseCommand):
    help = "Command just for testing purpose"

    def add_arguments(self, parser):
        parser.add_argument(
            "--test-str-required", type=str, required=True, default="default value"
        )
        parser.add_argument("--test-str-not-required", type=str, required=False)
        parser.add_argument("--test-bool-required", type=bool, required=True)
        parser.add_argument("--test-bool-not-required", type=bool, required=False)
        parser.add_argument("--test-int-required", type=int, required=True)
        parser.add_argument("--test-int-not-required", type=int, required=False)
        parser.add_argument("--test-array", action="append", required=False)

    def handle(self, *args, **options):
        log_event("started")

        test_str_required = options["test_str_required"]
        test_str_not_required = options["test_str_not_required"]
        test_bool_required = options["test_bool_required"]
        test_bool_not_required = options["test_bool_not_required"]
        test_int_required = options["test_int_required"]
        test_int_not_required = options["test_int_not_required"]
        test_array = options["test_array"]

        log_event("args retrieved")

        with open("test_cmd.txt", "w") as f:
            f.write("Hello this is the test_cmd file")
            f.write(f"test_str_required: {test_str_required}")
            f.write(f"test_str_not_required: {test_str_not_required}")
            f.write(f"test_bool_required: {test_bool_required}")
            f.write(f"test_bool_not_required: {test_bool_not_required}")
            f.write(f"test_int_required: {test_int_required}")
            f.write(f"test_int_not_required: {test_int_not_required}")
            f.write(f"test_array: {test_array.join(', ')}")

        log_event("test_cmd.txt file created and cmd finished")
