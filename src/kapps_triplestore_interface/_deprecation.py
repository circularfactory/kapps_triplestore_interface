"""The deprecated names of the interface: each use of one emits one `DeprecationWarning`.

The warning names the name that replaces the old one. The release that removes the deprecated
names removes this module.
"""

from __future__ import annotations

import functools
import warnings
from typing import Any, Callable, TypeVar, cast

_Function = TypeVar("_Function", bound=Callable[..., Any])


def renamed(successor: str) -> Callable[[_Function], _Function]:
    """Mark a function as the deprecated old name of `successor`.

    Each call warns once, at the caller's line, and then runs the function. The function keeps
    its name and its parameters. It carries `__deprecated__`, the attribute of PEP 702, with the
    message, so the documentation leaves it out.
    """

    def mark(function: _Function) -> _Function:
        message = (
            f"{function.__name__} is deprecated; use {successor}, which replaces it."
        )

        @functools.wraps(function)
        def alias(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            return function(*args, **kwargs)

        alias.__deprecated__ = message  # type: ignore[attr-defined]
        return cast(_Function, alias)

    return mark
