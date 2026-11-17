"""The deprecated names of the interface: each use of one emits one `DeprecationWarning`.

The warning names the name that replaces the old one. The release that removes the deprecated
names removes this module.
"""

from __future__ import annotations

import functools
import os
import warnings
from typing import Any, Callable, TypeVar, cast

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep

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


def unchecked_update(operation: str) -> None:
    """Warn that `operation` was called with `check_exist=False`, which 3.0.0 removes.

    The warning is attributed to the first frame outside this package, so the caller's line is
    reported whichever adapter forwarded the call. It changes nothing that is sent.
    """
    warnings.warn(
        f"{operation}(check_exist=False) sends an unchecked update: it returns True whether or "
        "not the update applied. Interface 3.0.0 always checks the update and removes the "
        "check_exist parameter of the update operations. Leave out check_exist (or pass "
        "check_exist=True) to have a write that reports its outcome.",
        DeprecationWarning,
        skip_file_prefixes=(_PACKAGE_DIR,),
    )
