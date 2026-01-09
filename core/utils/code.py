from typing import Optional


def find_missing_variables(error_prefix: Optional[str] = None, **kwargs):
    missing_variables = set()

    for name, value in kwargs.items():
        if value is None:
            missing_variables.add(name)

    if not missing_variables:
        return

    raise ValueError(
        f"{error_prefix + ', ' if error_prefix else ''}missing variables: {', '.join(missing_variables)}"
    )
