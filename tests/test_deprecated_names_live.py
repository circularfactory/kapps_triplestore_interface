"""Each old name still works against a real GraphDB, and each use of one warns once.

The test requests the `db` fixture, so it is in the `live` tier: it runs where the suite's store
is configured, as in CI, and skips elsewhere. `test_deprecated_names.py` covers the same names
without a store. The other tests of the suite call the renamed operations, the attribute and
the error by their new names. The suite's `db` fixture builds its store with `connect()`; the
`GraphDBCredentials` here are built from the `TRIPLESTORE_*` variables, explicitly, because that
construction is what the test is about.
"""

from __future__ import annotations

import importlib
import warnings
from typing import Callable

import pytest

from kapps_triplestore_interface import GraphDB

GRAPH = "http://example.org/deprecated_names_graph"
STATEMENT = (
    "<http://example.org/deprecated_names#s> <http://example.org/deprecated_names#p>"
    ' "o" .\n'
)


def _once(action: Callable[[], object], old: str, new: str) -> object:
    """Run `action`; it must emit exactly one deprecation warning, which names `old` and `new`."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = action()
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == 1, [str(w.message) for w in deprecations]
    assert old in str(deprecations[0].message)
    assert new in str(deprecations[0].message)
    return result


@pytest.fixture(name="graph")
def _graph(db: GraphDB):
    db.graph_clear(GRAPH)
    yield GRAPH
    db.graph_clear(GRAPH)


def test_each_old_name_still_works_against_the_store_and_warns_once(
    db, graph, store_settings
):
    added = _once(
        lambda: db.import_statements(STATEMENT, graph_iri=graph),
        "import_statements",
        "graph_add",
    )
    assert added is True

    fetched = _once(lambda: db.fetch_statements(graph), "fetch_statements", "graph_get")
    assert len(fetched) == 1

    graphs = _once(
        db.get_list_of_named_graphs, "get_list_of_named_graphs", "graphs_get"
    )
    assert graph in [str(g) for g in graphs]

    datasets = _once(
        lambda: db.get_list_of_repositories(only_ids=True),
        "get_list_of_repositories",
        "datasets_get",
    )
    assert db.dataset in datasets

    assert _once(lambda: db.repository, "repository", "dataset") == db.dataset

    cleared = _once(lambda: db.clear_graph(graph), "clear_graph", "graph_clear")
    assert cleared is True
    assert len(db.graph_get(graph)) == 0

    credentials_type = _once(
        lambda: importlib.import_module(
            "kapps_triplestore_interface"
        ).GraphDBCredentials,
        "GraphDBCredentials",
        "TripleStoreEndpoint",
    )
    credentials = credentials_type(
        base_url=store_settings["base_url"],
        username=store_settings["username"],
        password=store_settings["password"],
        repository=db.dataset,
    )
    # GDB token, the mode of the stores that this suite runs against: Basic authentication
    # answers 401 on a store with security on.
    client = _once(
        lambda: GraphDB(credentials=credentials, use_gdb_token=True),
        "use_gdb_token",
        "GDBTokenAuth",
    )
    assert client.graph_get(graph) is not None
    client.close()

    missing_type = _once(
        lambda: importlib.import_module(
            "kapps_triplestore_interface.exceptions"
        ).InvalidRepositoryError,
        "InvalidRepositoryError",
        "InvalidDatasetError",
    )
    with pytest.raises(missing_type):
        GraphDB(
            credentials=credentials_type(
                base_url=store_settings["base_url"],
                username=store_settings["username"],
                password=store_settings["password"],
                repository="deprecated-names-no-such-dataset",
            )
        )
