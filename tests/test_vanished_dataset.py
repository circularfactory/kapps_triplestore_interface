"""A dataset deleted after `connect()` raises `InvalidDatasetError`, as `connect()` does.

The store answers a request to a dataset that it does not have with 404 and
`Unknown repository: <dataset>` (RDF4J's answer, which GraphDB gives). The adapter recognises
the unknown dataset from that answer, not from the status alone: a 404 with another meaning,
such as a named graph that the graph store does not have, keeps its type.

These tests run without a triple store. The stub in `_stub_store.py` answers as GraphDB does.
"""

from __future__ import annotations

import pytest

from kapps_triplestore_interface import (
    BasicAuth,
    GraphDB,
    TripleStoreEndpoint,
    TripleStoreResponseError,
)
from kapps_triplestore_interface.exceptions import InvalidDatasetError
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    answer,
    store,
)

QUERY = f"/repositories/{DATASET}"
UPDATE = f"/repositories/{DATASET}/statements"
GRAPH_STORE = f"/repositories/{DATASET}/rdf-graphs/service"
UNKNOWN = f"Unknown repository: {DATASET}"
GRAPH = "http://example.org/graphs#missing"


@pytest.fixture
def adapter(store) -> GraphDB:
    return GraphDB(
        endpoint=TripleStoreEndpoint(url=BASE_URL, dataset=DATASET),
        auth=BasicAuth(USERNAME, PASSWORD),
    )


@pytest.mark.parametrize(
    ("path", "operation"),
    [
        pytest.param(QUERY, lambda db: db.query("ASK {}"), id="a read"),
        pytest.param(
            UPDATE,
            lambda db: db.query("INSERT DATA {}", update=True),
            id="an update",
        ),
        pytest.param(GRAPH_STORE, lambda db: db.graph_get(GRAPH), id="graph_get"),
    ],
)
def test_a_request_to_a_dataset_the_store_does_not_know_raises_the_dataset_error(
    store, adapter, path, operation
):
    store.answers[path] = answer(404, UNKNOWN)

    with pytest.raises(InvalidDatasetError) as missing:
        operation(adapter)

    message = str(missing.value)
    assert f"'{DATASET}'" in message
    assert BASE_URL in message
    assert f"(404) - {UNKNOWN}" in message


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("", id="an empty answer"),
        pytest.param(f"No such graph: {GRAPH}", id="another answer"),
        pytest.param(f"Unknown repository: {DATASET}-other", id="another dataset"),
    ],
)
def test_a_404_with_another_meaning_keeps_its_type(store, adapter, body):
    store.answers[GRAPH_STORE] = answer(404, body)

    with pytest.raises(TripleStoreResponseError) as failed:
        adapter.graph_get(GRAPH)

    assert type(failed.value) is TripleStoreResponseError
    assert failed.value.status == 404
