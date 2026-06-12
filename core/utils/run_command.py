from typing import Any, Dict, List, Optional, TypedDict, Union
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


# argparse flag actions (store_true/store_false/BooleanOptionalAction) carry no
# `type`, so without this they'd be reported as "str" and the admin run-command form
# would render a free-text input instead of a checkbox.
BOOLEAN_ACTION_NAMES = {
    "_StoreTrueAction",
    "_StoreFalseAction",
    "BooleanOptionalAction",
}


def _resolve_parameter_type(action) -> str:
    if type(action).__name__ in BOOLEAN_ACTION_NAMES:
        return "bool"
    if action.type is not None:
        return action.type.__name__
    return "str"


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
                        type=_resolve_parameter_type(action),
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


def _coerce_scalar(value: Any, type_name: str) -> Any:
    """Coerce a single value to the parameter's declared type.

    call_command() does NOT run kwargs through argparse, so a value keeps whatever JSON
    type it arrived with (the admin form / JSON editor can send a number for a str-typed
    option, or a string for an int-typed one). Coercing here mirrors what argparse does
    on the CLI, where ``type=int``/``type=str`` always yield an int/str. It matters: an
    int-typed option compared against an integer column in raw SQL fails if it stays a
    string, and a str-typed option (e.g. --batch-id) sent as a number fails the reverse
    way ("character varying = integer"). ``bool`` guards against int(True) -> 1 / the
    str cast, though bool params never reach these branches.
    """
    if isinstance(value, bool):
        return value
    if type_name == "int":
        return int(value)
    if type_name == "str":
        return str(value)
    return value


def _parse_multiple(value: Any, type_name: str) -> List[Any]:
    """Normalize a repeatable parameter to a typed list.

    The admin form sends a single comma-separated string ("1,2,3"); the JSON editor can
    send a real list; a lone scalar (e.g. an int from a NumberInput) is wrapped. Empty
    fragments from trailing/double commas are dropped.
    """
    if isinstance(value, str):
        items = [fragment.strip() for fragment in value.split(",")]
        items = [fragment for fragment in items if fragment]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = [value]

    return [_coerce_scalar(item, type_name) for item in items]


def parse_parameters(
    command_name: str, parameters: CommandParameters
) -> CommandParameters:
    command_parameters_map = COMMANDS_AND_PARAMETERS_MAP.get(command_name)
    if not command_parameters_map:
        raise BadRequest(f"Command with name '{command_name}' not found")

    parsed_parameters = parameters.copy()

    for parameter_name, param_config in command_parameters_map.items():
        parameter_value = parsed_parameters.get(parameter_name)

        if param_config["required"] and parameter_value is None:
            raise BadRequest(
                f"Parameter with name '{command_name}.{parameter_name}' is required"
            )

        if parameter_value is None:
            continue

        type_name = param_config.get("type", "str")

        try:
            if param_config["multiple"]:
                parsed_parameters[parameter_name] = _parse_multiple(
                    parameter_value, type_name
                )
            else:
                parsed_parameters[parameter_name] = _coerce_scalar(
                    parameter_value, type_name
                )
        except (ValueError, TypeError):
            expected = (
                f"a list of {type_name} values"
                if param_config["multiple"]
                else f"a {type_name} value"
            )
            raise BadRequest(
                f"Parameter '{command_name}.{parameter_name}' expects {expected}"
            )

    return parsed_parameters
