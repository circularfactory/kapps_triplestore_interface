"""The environment from which a store is built: `TRIPLESTORE_*`, and `GRAPHDB_*` as a fallback.

Each `TRIPLESTORE_*` variable has one `GRAPHDB_*` variable as its deprecated fallback. A value
read from the fallback emits one `DeprecationWarning` that names the variable which replaces it.
The contract release removes the fallback.
"""

from __future__ import annotations

import os
import warnings

# Each variable, and the deprecated variable that is read when it is not set.
FALLBACKS = {
    "TRIPLESTORE_URL": "GRAPHDB_URL",
    "TRIPLESTORE_DATASET": "GRAPHDB_REPOSITORY",
    "TRIPLESTORE_USERNAME": "GRAPHDB_USERNAME",
    "TRIPLESTORE_PASSWORD": "GRAPHDB_PASSWORD",
}


def read(name: str) -> str:
    """The value of the variable `name`, or of its fallback, with a warning.

    An empty value counts as not set.

    Raises:
        ValueError: If neither the variable nor its fallback is set. The message names the
            variable.
    """
    value = os.environ.get(name)
    if value:
        return value
    fallback = FALLBACKS[name]
    value = os.environ.get(fallback)
    if value:
        warnings.warn(
            f"{fallback} is deprecated; set {name}, which replaces it.",
            DeprecationWarning,
            stacklevel=3,
        )
        return value
    raise ValueError(f"{name} environment variable is not set.")
