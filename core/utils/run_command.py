from typing import Dict, List, Optional, TypedDict, Union
from django.core.management import get_commands, load_command_class
from django.core.management.base import BaseCommand
from django.core.exceptions import BadRequest


DEFAULT_OPTIONS = {
    "--version",
    "--verbosity",
    "--settings",
    "--pythonpath",
    "--traceback",
    "--no-color",
    "--force-color",
    "--skip-checks",
    "--help",
}


class CommandParameters(TypedDict):
    name: str
    type: str
    default: str
    multiple: bool
    required: bool


class CommandWithParameters(TypedDict):
    name: str
    help: Optional[str]
    parameters: List[CommandParameters]


def list_commands_with_parameters() -> List[CommandWithParameters]:
    commands = []

    for command_name, app_name in sorted(get_commands().items()):
        if app_name != "core":
            continue

        try:
            command_obj = load_command_class(app_name, command_name)
            command = CommandWithParameters(
                name=command_name, parameters=[], help=command_obj.help
            )
            if isinstance(command_obj, BaseCommand):
                parser = command_obj.create_parser("manage.py", command_name)

                for action in parser._actions:
                    if any(opt in DEFAULT_OPTIONS for opt in action.option_strings):
                        continue

                    opts = (
                        ", ".join(action.option_strings)
                        if action.option_strings
                        else action.dest
                    )
                    command_parameters = CommandParameters(
                        name=opts,
                        type=action.type.__name__ if action.type else "str",
                        default=action.default,
                        required=action.required,
                        multiple=type(action).__name__ == "_AppendAction",
                    )
                    command["parameters"].append(command_parameters)

            commands.append(command)
        except Exception as e:
            print(f"Error loading {command_name}: {e}")

    return commands


COMMANDS_AND_PARAMETERS = list_commands_with_parameters()
COMMANDS_AND_PARAMETERS_MAP = {
    command["name"]: {param["name"]: param for param in command["parameters"]}
    for command in COMMANDS_AND_PARAMETERS
}

CommandParameters = Dict[str, Union[bool, str, int]]


def parse_parameters(
    command_name: str, parameters: CommandParameters
) -> CommandParameters:
    command_parameters_map = COMMANDS_AND_PARAMETERS_MAP.get(command_name)
    if not command_parameters_map:
        raise BadRequest(f"Command with name '{command_name}' not found")

    parsed_parameters = parameters.copy()

    for parameter_name, param_config in command_parameters_map.items():
        parameter_value = parsed_parameters.get(parameter_name)
        if not param_config:
            raise BadRequest(
                f"Command with name '{command_name}' does not have parameter '{parameter_name}'"
            )

        if param_config["required"] and parameter_value is None:
            raise BadRequest(
                f"Parameter with name '{command_name}.{parameter_name}' is required"
            )

        if param_config["multiple"] and parameter_value:
            parsed_parameters[parameter_name] = parsed_parameters[parameter_name].split(
                ","
            )

    return parsed_parameters
