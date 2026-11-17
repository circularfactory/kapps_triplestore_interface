"""The one place where the examples connect to the GraphDB.

Every example opens its store through ``open_store``. The configuration comes from the
``TRIPLESTORE_URL``, ``TRIPLESTORE_DATASET``, ``TRIPLESTORE_USERNAME`` and ``TRIPLESTORE_PASSWORD``
variables. Where one is not set, the default matches the compose file in ``docker/``: a GraphDB on
``http://localhost:7200`` with the built-in ``admin`` user and the repository ``kapps-demo``.

Each example writes into a graph of its own and clears that graph when it starts. Never point
the examples at a repository whose data you care about.
"""

from __future__ import annotations

import os

from kapps_triplestore_interface import (
    GDBTokenAuth,
    TripleStore,
    TripleStoreEndpoint,
    connect,
)

NAMESPACE = "http://example.org/examples#"
"""The namespace of every name that the examples invent."""

GRAPH_BASE = "http://example.org/examples/graphs/"


def graph_name(example: str) -> str:
    """The name of the graph in which the example ``example`` keeps its data."""
    return f"{GRAPH_BASE}{example}"


def endpoint_from_environment() -> TripleStoreEndpoint:
    """The endpoint: ``TRIPLESTORE_URL`` and ``TRIPLESTORE_DATASET``, else the compose file's."""
    return TripleStoreEndpoint(
        url=os.environ.get("TRIPLESTORE_URL", "http://localhost:7200"),
        dataset=os.environ.get("TRIPLESTORE_DATASET", "kapps-demo"),
    )


def open_store() -> TripleStore:
    """Connect to the store that the ``TRIPLESTORE_*`` variables name, else the compose file's."""
    endpoint = endpoint_from_environment()
    auth = GDBTokenAuth(
        os.environ.get("TRIPLESTORE_USERNAME", "admin"),
        os.environ.get("TRIPLESTORE_PASSWORD", "root"),
    )
    return connect(endpoint, auth)
