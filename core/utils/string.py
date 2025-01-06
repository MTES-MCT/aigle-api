from enum import Enum
import re
from typing import List, Optional, Type, TypeVar
import unicodedata


def snake_to_camel_case(name: str) -> str:
    parts = iter(name.split("_"))
    return next(parts) + "".join(i.title() for i in parts)


def strip_accents(text):
    """
    Strip accents from input String.

    :param text: The input string.
    :type text: String.

    :returns: The processed String.
    :rtype: String.
    """
    text = unicodedata.normalize("NFD", text)
    text = text.encode("ascii", "ignore")
    text = text.decode("utf-8")
    return str(text)


def normalize(string: str) -> str:
    res = re.sub(
        "[^a-zA-Z0-9 \n\\.]", " ", unicodedata.normalize("NFD", strip_accents(string))
    ).lower()

    return " ".join(res.split())


def slugify(string: str) -> str:
    normalized = normalize(string)
    spliteds = [splited for splited in normalized.split(" ") if splited]

    return "-".join(spliteds)


def to_array(string: str, sep: str = ",", default_value=None):
    if not string:
        return default_value

    return string.split(sep=sep) or default_value


E_TYPE = TypeVar("E_TYPE", bound=Enum)


def to_enum_array(
    enum_class: Type[E_TYPE], string: str, sep: str = ",", default_value=None
) -> List[E_TYPE]:
    str_array = to_array(string=string, sep=sep)

    if not str_array:
        return default_value

    result: List[E_TYPE] = []

    for str_elt in str_array:
        try:
            enum_member = enum_class[str_elt]
            result.append(enum_member)
        except KeyError:
            raise ValueError(
                f"'{string}' is not a valid member of {enum_class.__name__}"
            )

    return result


def to_bool(string: str) -> Optional[bool]:
    string_lower = string.lower()

    if string_lower == "true":
        return True

    if string_lower == "false":
        return False

    return None
