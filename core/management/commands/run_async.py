# management/commands/run_async.py

from typing import Any, List, Optional
from django.core.management.base import BaseCommand, CommandParser

from core.utils.tasks import AsyncCommandService


class Command(BaseCommand):
    help = "Run Django management commands asynchronously"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("command", type=str, help="Command to run")
        parser.add_argument("--args", nargs="*", default=[], help="Command arguments")
        parser.add_argument("--wait", action="store_true", help="Wait for completion")

    def handle(self, *args: Any, **options: Any) -> None:
        command_name: str = options["command"]
        command_args: List[str] = options.get("args", [])
        wait: bool = options.get("wait", False)

        task_id: str = AsyncCommandService.run_command_async(
            command_name, *command_args
        )
        self.stdout.write(f"Task started with ID: {task_id}")

        if wait:
            self.stdout.write("Waiting for completion...")
            result: Optional[Any] = AsyncCommandService.get_task_result(task_id)
            while result is None:
                import time

                time.sleep(1)
                result = AsyncCommandService.get_task_result(task_id)

            self.stdout.write("Task completed:")
            self.stdout.write(str(result))
