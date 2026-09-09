from enum import Enum
import re
from typing import List, Optional, Type, TypeVar
import unicodedata


def strip_accents(text: str) -> str:
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


def strip_email_subaddress(email: str) -> str:
    """stephen+xyz@mail.com -> stephen@mail.com

    Les comptes de test sont créés en sous-adressant une boîte unique. Tous les
    fournisseurs ne routent pas le suffixe `+`, donc on l'enlève à l'envoi plutôt que
    de compter dessus. L'adresse du compte, elle, n'est jamais modifiée : c'est
    l'identifiant de connexion.
    """
    local, separator, domain = email.rpartition("@")

    if not separator:
        return email

    stripped_local = local.split("+", 1)[0]

    # "+xyz@mail.com" donnerait "@mail.com" : mieux vaut tenter l'adresse d'origine.
    if not stripped_local:
        return email

    return f"{stripped_local}@{domain}"


def to_array(
    string: str, sep: str = ",", default_value: Optional[List[str]] = None
) -> Optional[List[str]]:
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


def to_bool(string: Optional[str]) -> Optional[bool]:
    if string is None:
        return None

    string_lower = string.lower()

    if string_lower == "true":
        return True

    if string_lower == "false":
        return False

    return None
