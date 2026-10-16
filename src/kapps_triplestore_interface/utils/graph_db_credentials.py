"""The deprecated credentials of a GraphDB store.

`GraphDBCredentials` is a deprecated name: a `TripleStoreEndpoint` and an auth provider,
`GDBTokenAuth` or `BasicAuth`, replace it. Each use of the name emits one `DeprecationWarning`
that names them. A client built from the credentials builds the endpoint and the provider from
them.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import warnings
from typing import TYPE_CHECKING, Any

_DEPRECATION = (
    "GraphDBCredentials is deprecated; use TripleStoreEndpoint and an auth provider,"
    " GDBTokenAuth or BasicAuth, which replace it."
)


@dataclass(frozen=True)
class GraphDBCredentials:
    """
    Immutable credentials for connecting to a GraphDB instance.

    Contains the base URL, user credentials, and target repository used by
    the client to authenticate and perform SPARQL operations.

    Args:
        base_url (str): Base URL of the GraphDB instance (e.g., "http://localhost:7200").
        username (str): Username for GraphDB authentication.
        password (str): Password for GraphDB authentication.
        repository (str): Repository identifier to target within the instance.
    """

    base_url: str
    username: str
    password: str
    repository: str

    @classmethod
    def from_env(cls) -> GraphDBCredentials:
        """
        Build credentials from environment variables.

        The following environment variables must be set: `GRAPHDB_USERNAME`,
        `GRAPHDB_PASSWORD`, `GRAPHDB_URL`, and `GRAPHDB_REPOSITORY`.

        Returns:
            GraphDBCredentials: A credentials instance populated from the environment.

        Raises:
            ValueError: If any of the required environment variables are missing.
        """

        if os.getenv("GRAPHDB_USERNAME") is None:
            raise ValueError("GRAPHDB_USERNAME environment variable is not set.")
        if os.getenv("GRAPHDB_PASSWORD") is None:
            raise ValueError("GRAPHDB_PASSWORD environment variable is not set.")
        if os.getenv("GRAPHDB_URL") is None:
            raise ValueError("GRAPHDB_URL environment variable is not set.")
        if os.getenv("GRAPHDB_REPOSITORY") is None:
            raise ValueError("GRAPHDB_REPOSITORY environment variable is not set.")

        username = os.getenv("GRAPHDB_USERNAME")
        password = os.getenv("GRAPHDB_PASSWORD")
        base_url = os.getenv("GRAPHDB_URL")
        repository = os.getenv("GRAPHDB_REPOSITORY")

        return cls(
            base_url=base_url,
            username=username,
            password=password,
            repository=repository,
        )


# The class under a private name, for the interface's own use, which must not warn: the adapter
# reads the credentials, and `GraphDB.from_env()` builds them. The public name is not an
# attribute of the module, so that each use of it goes through `__getattr__` and warns. A type
# checker reads it as the class.
_GraphDBCredentials = GraphDBCredentials
if not TYPE_CHECKING:
    del GraphDBCredentials


def __getattr__(name: str) -> Any:
    if name != "GraphDBCredentials":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)
    return _GraphDBCredentials
