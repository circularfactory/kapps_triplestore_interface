"""An import that the store does not accept raises, and a normal return means it accepted it.

These tests run without a triple store. The stub in `_stub_store.py` answers the graph-store
endpoint as the test says, so every request goes through the adapter's own request path. They
cover POST (append) and PUT (overwrite), each for a named graph and for the default graph.
The live half is in `test_import_statements_live.py`.
"""

from __future__ import annotations

import logging

import pytest

from kapps_triplestore_interface import (
    AuthenticationError,
    GDBTokenAuth,
    GraphDB,
    ShaclValidationError,
    TripleStoreAccessError,
    TripleStoreEndpoint,
)
from kapps_triplestore_interface.exceptions import TripleStoreResponseError
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    answer,
    store,
)

EX = "http://example.org/import-refusal#"
GRAPH = f"{EX}graph"
CONTENT = f"<{EX}thing> <{EX}part> <{EX}one> ."
GRAPH_STORE = f"/repositories/{DATASET}/rdf-graphs/service"

SHACL_MEDIA_TYPE = "application/shacl-validation-report+n-quads;charset=UTF-8"
REPORT = f"""\
_:r <http://www.w3.org/ns/shacl#conforms> "false"^^<http://www.w3.org/2001/XMLSchema#boolean> .
_:r <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/ns/shacl#ValidationReport> .
_:r <http://www.w3.org/ns/shacl#result> _:v .
_:v <http://www.w3.org/ns/shacl#focusNode> <{EX}thing> .
_:v <http://www.w3.org/ns/shacl#resultPath> <{EX}part> .
"""

# POST and PUT, for a named graph and for the default graph.
EACH_IMPORT = pytest.mark.parametrize(
    ("overwrite", "graph", "method", "path", "target"),
    [
        (False, GRAPH, "POST", GRAPH_STORE, f"graph <{GRAPH}>"),
        (True, GRAPH, "PUT", GRAPH_STORE, f"graph <{GRAPH}>"),
        (False, None, "POST", f"{GRAPH_STORE}?default", "the default graph"),
        (True, None, "PUT", f"{GRAPH_STORE}?default", "the default graph"),
    ],
    ids=["post-named", "put-named", "post-default", "put-default"],
)


def _adapter() -> GraphDB:
    return GraphDB(
        endpoint=TripleStoreEndpoint(url=BASE_URL, dataset=DATASET),
        auth=GDBTokenAuth(USERNAME, PASSWORD),
    )


def _imports(store) -> list[tuple[str, str]]:
    """The method and path of each import that the store received."""
    return [
        (method, path) for method, path, _ in store.sent if path.startswith(GRAPH_STORE)
    ]


@EACH_IMPORT
def test_an_import_the_store_accepts_returns_true(
    store, overwrite, graph, method, path, target
):
    store.answers[path] = answer(204)

    assert _adapter().graph_add(CONTENT, overwrite, graph) is True

    assert _imports(store) == [(method, path)]
    assert store.bodies[-1] == CONTENT


@EACH_IMPORT
def test_a_validation_report_raises_the_shacl_type_with_the_report_verbatim(
    store, overwrite, graph, method, path, target
):
    store.answers[path] = answer(500, REPORT, SHACL_MEDIA_TYPE)

    with pytest.raises(ShaclValidationError) as refused:
        _adapter().graph_add(CONTENT, overwrite, graph)

    assert refused.value.report == REPORT
    assert refused.value.status == 500
    assert str(refused.value) == (
        f"Failed to import into {target} in repository '{DATASET}' (500) - {REPORT}"
    )
    assert isinstance(refused.value, TripleStoreResponseError)


@EACH_IMPORT
def test_a_refusal_logs_the_report_at_debug_and_nothing_louder(
    store, caplog, overwrite, graph, method, path, target
):
    store.answers[path] = answer(500, REPORT, SHACL_MEDIA_TYPE)
    db = _adapter()
    caplog.clear()

    with caplog.at_level(logging.DEBUG), pytest.raises(ShaclValidationError):
        db.graph_add(CONTENT, overwrite, graph)

    assert [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.INFO
    ] == []


@EACH_IMPORT
@pytest.mark.parametrize(
    ("status", "media_type", "body", "error_type"),
    [
        (
            400,
            "text/plain;charset=UTF-8",
            "MALFORMED DATA: line 1",
            TripleStoreResponseError,
        ),
        (403, "text/plain;charset=UTF-8", "Forbidden", TripleStoreAccessError),
        (500, "text/plain;charset=UTF-8", "Unknown error", TripleStoreResponseError),
        (
            503,
            "text/html",
            "<html>Service Unavailable</html>",
            TripleStoreResponseError,
        ),
    ],
    ids=["malformed", "forbidden", "server-error", "unavailable"],
)
def test_every_other_error_answer_raises_its_type_with_the_status_and_the_body(
    store, overwrite, graph, method, path, target, status, media_type, body, error_type
):
    store.answers[path] = answer(status, body, media_type)

    with pytest.raises(TripleStoreResponseError) as failed:
        _adapter().graph_add(CONTENT, overwrite, graph)

    assert type(failed.value) is error_type
    assert failed.value.status == status
    assert str(failed.value) == (
        f"Failed to import into {target} in repository '{DATASET}' ({status}) - {body}"
    )


@EACH_IMPORT
def test_an_error_answer_other_than_a_refusal_logs_at_error(
    store, caplog, overwrite, graph, method, path, target
):
    store.answers[path] = answer(500, "Unknown error")
    db = _adapter()
    caplog.clear()

    with caplog.at_level(logging.DEBUG), pytest.raises(TripleStoreResponseError):
        db.graph_add(CONTENT, overwrite, graph)

    assert [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.levelno >= logging.INFO
    ] == [
        (
            "ERROR",
            f"Failed to import into {target} in repository '{DATASET}' (500) - Unknown error",
        )
    ]


@EACH_IMPORT
def test_a_second_401_after_the_login_raises_authentication_error(
    store, overwrite, graph, method, path, target
):
    """The adapter logs in again once after a 401. A second 401 raises; it was `False` before."""
    store.answers[path] = answer(401, "Unauthorized")

    with pytest.raises(AuthenticationError) as refused:
        _adapter().graph_add(CONTENT, overwrite, graph)

    assert refused.value.status == 401
    assert str(refused.value) == (
        f"Failed to import into {target} in repository '{DATASET}' (401) - Unauthorized"
    )
    assert store.paths() == ["/rest/login", path, "/rest/login", path]
