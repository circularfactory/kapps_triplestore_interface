"""The store registries: a dataset's prefixes, and the SHACL shapes that it validates against.

These tests run without a triple store. The stub in `_stub_store.py` answers as GraphDB does;
each test sets the answer that it needs. The adapter is built from an endpoint and Basic
authentication, so it sends no request when it is built, and no login: each request that the
stub records is one of the operation.

- **Prefixes:** RDF4J's namespace requests on the dataset. The empty prefix has the address
  `namespaces/`, with the slash: `namespaces` without it is the address of every prefix, and a
  DELETE there deletes them all.
- **Shapes:** the adapter reads the repository configuration first. On a dataset without SHACL
  validation it raises `TripleStoreNotSupportedError` and sends nothing else. Otherwise it
  replaces RDF4J's shapes graph with the new document in one graph-store PUT, which the store
  applies whole or not at all. An empty document is one DELETE of the shapes graph.

The detection of SHACL validation is one internal function, `_shacl_validation_on`, tested
here for each answer that the configuration can give. Its input follows GraphDB's documentation
of its REST API, and GraphDB 10.8.5 answers it so: `isShacl` is true for a repository whose
store is wrapped in an `rdf4j:ShaclSail`, and false for a plain `graphdb:Sail`.
"""

# pytest passes the fixtures by name, and an exact type is what these tests check.
# pylint: disable=redefined-outer-name,unused-argument,unidiomatic-typecheck

from __future__ import annotations

import json
from typing import Dict

import pytest

from kapps_triplestore_interface import (
    BasicAuth,
    AuthenticationError,
    GraphDB,
    ShaclValidationError,
    TripleStore,
    TripleStoreAccessError,
    TripleStoreEndpoint,
    TripleStoreNotSupportedError,
    TripleStoreResponseError,
)
from kapps_triplestore_interface.exceptions import InvalidDatasetError
from kapps_triplestore_interface.graph_db import _shacl_validation_on
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    answer,
    store,
)

NAMESPACES = f"/repositories/{DATASET}/namespaces"
CONFIGURATION = f"/rest/repositories/{DATASET}"
GRAPH_STORE = f"/repositories/{DATASET}/rdf-graphs/service"
SHAPES_GRAPH = "http://rdf4j.org/schema/rdf4j#SHACLShapeGraph"
EX = "http://example.org/registry#"
SHAPES = f"""<{EX}ThingShape> a <http://www.w3.org/ns/shacl#NodeShape> ;
    <http://www.w3.org/ns/shacl#targetClass> <{EX}Thing> .
"""
BODY = "the store's answer, unchanged"


@pytest.fixture
def adapter(store) -> GraphDB:
    """The adapter, built after the stub, so that every request reaches the stub."""
    return GraphDB(
        endpoint=TripleStoreEndpoint(url=BASE_URL, dataset=DATASET),
        auth=BasicAuth(USERNAME, PASSWORD),
    )


def _namespaces_answer(prefixes: Dict[str, str]):
    """GraphDB's answer to a read of the namespaces: SPARQL JSON results."""
    bindings = [
        {
            "prefix": {"type": "literal", "value": prefix},
            "namespace": {"type": "literal", "value": namespace},
        }
        for prefix, namespace in prefixes.items()
    ]
    return answer(
        200,
        json.dumps(
            {
                "head": {"vars": ["prefix", "namespace"]},
                "results": {"bindings": bindings},
            }
        ),
        "application/sparql-results+json",
    )


def _configuration(**params: object) -> dict:
    """A repository configuration as GraphDB's REST API answers it, with `params`."""
    return {
        "id": DATASET,
        "title": "",
        "type": "graphdb",
        "sesameType": "graphdb:SailRepository",
        "location": "",
        "params": {
            name: {"name": name, "label": name, "value": value}
            for name, value in params.items()
        },
    }


def _configuration_answer(**params: object):
    return answer(200, json.dumps(_configuration(**params)), "application/json")


WITH_SHACL = {"isShacl": "true", "validationEnabled": "true"}
WITHOUT_SHACL = {"isShacl": "false", "validationEnabled": "true"}


# -- prefixes_get ------------------------------------------------------------------------------


def test_prefixes_get_reads_the_namespaces_of_the_dataset(store, adapter):
    store.answers[NAMESPACES] = _namespaces_answer(
        {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "": EX}
    )

    prefixes = adapter.prefixes_get()

    assert prefixes == {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "": EX}
    assert store.sent == [("GET", NAMESPACES, store.sent[0][2])]
    assert store.headers[0]["Accept"] == "application/sparql-results+json"


def test_prefixes_get_of_a_dataset_without_prefixes_is_empty(store, adapter):
    store.answers[NAMESPACES] = _namespaces_answer({})

    assert adapter.prefixes_get() == {}


# -- prefix_set --------------------------------------------------------------------------------


def test_prefix_set_puts_the_iri_at_the_address_of_the_prefix(store, adapter):
    store.answers[f"{NAMESPACES}/ex"] = answer(204)

    assert adapter.prefix_set("ex", EX) is None

    assert [(method, path) for method, path, _ in store.sent] == [
        ("PUT", f"{NAMESPACES}/ex")
    ]
    assert store.bodies == [EX]
    assert store.headers[0]["Content-Type"] == "text/plain"


def test_prefix_set_of_the_empty_prefix_puts_at_the_address_with_the_slash(
    store, adapter
):
    store.answers[f"{NAMESPACES}/"] = answer(204)

    adapter.prefix_set("", EX)

    assert [(method, path) for method, path, _ in store.sent] == [
        ("PUT", f"{NAMESPACES}/")
    ]
    assert store.bodies == [EX]


def test_prefix_set_quotes_a_prefix_so_that_it_stays_one_path_segment(store, adapter):
    store.answers[f"{NAMESPACES}/a%2Fb%3Fc"] = answer(204)

    adapter.prefix_set("a/b?c", EX)

    assert store.paths() == [f"{NAMESPACES}/a%2Fb%3Fc"]


# -- prefix_delete -----------------------------------------------------------------------------


def test_prefix_delete_deletes_at_the_address_of_the_prefix(store, adapter):
    store.answers[f"{NAMESPACES}/ex"] = answer(204)

    assert adapter.prefix_delete("ex") is None

    assert [(method, path) for method, path, _ in store.sent] == [
        ("DELETE", f"{NAMESPACES}/ex")
    ]


def test_prefix_delete_of_the_empty_prefix_never_deletes_every_prefix(store, adapter):
    """`namespaces` without the slash is the address of every prefix."""
    store.answers[f"{NAMESPACES}/"] = answer(204)

    adapter.prefix_delete("")

    assert [(method, path) for method, path, _ in store.sent] == [
        ("DELETE", f"{NAMESPACES}/")
    ]


# -- the error answers of the prefix operations ------------------------------------------------


PREFIX_OPERATIONS = pytest.mark.parametrize(
    ("operation", "path"),
    [
        (lambda db: db.prefixes_get(), NAMESPACES),
        (lambda db: db.prefix_set("ex", EX), f"{NAMESPACES}/ex"),
        (lambda db: db.prefix_delete("ex"), f"{NAMESPACES}/ex"),
    ],
    ids=["prefixes_get", "prefix_set", "prefix_delete"],
)


@PREFIX_OPERATIONS
@pytest.mark.parametrize(
    ("status", "error_type"),
    [(400, TripleStoreResponseError), (403, TripleStoreAccessError)],
)
def test_an_error_answer_raises_the_type_of_its_status_with_the_answer(
    store, adapter, operation, path, status, error_type
):
    store.answers[path] = answer(status, BODY)

    with pytest.raises(error_type) as failed:
        operation(adapter)

    assert type(failed.value) is error_type
    assert failed.value.status == status
    assert str(failed.value).endswith(f"({status}) - {BODY}")
    assert f"'{DATASET}'" in str(failed.value)


# -- shapes_set --------------------------------------------------------------------------------


def _requests(store) -> list[tuple[str, str, object]]:
    return [
        (method, path, params)
        for (method, path, _), params in zip(store.sent, store.params)
    ]


def test_shapes_set_replaces_the_shapes_graph_in_one_put(store, adapter):
    store.answers[CONFIGURATION] = _configuration_answer(**WITH_SHACL)
    store.answers[GRAPH_STORE] = answer(204)

    assert adapter.shapes_set(SHAPES, "text/turtle") is None

    assert _requests(store) == [
        ("GET", CONFIGURATION, None),
        ("PUT", GRAPH_STORE, {"graph": SHAPES_GRAPH}),
    ]
    assert store.bodies[1] == SHAPES
    assert store.headers[1]["Content-Type"] == "text/turtle"


@pytest.mark.parametrize("empty", ["", "  \n\t"])
def test_shapes_set_with_an_empty_document_only_clears_the_shapes_graph(
    store, adapter, empty
):
    store.answers[CONFIGURATION] = _configuration_answer(**WITH_SHACL)
    store.answers[GRAPH_STORE] = answer(204)

    adapter.shapes_set(empty, "text/turtle")

    assert _requests(store) == [
        ("GET", CONFIGURATION, None),
        ("DELETE", GRAPH_STORE, {"graph": SHAPES_GRAPH}),
    ]


def test_shapes_set_on_a_dataset_without_shacl_raises_and_sends_nothing_else(
    store, adapter
):
    store.answers[CONFIGURATION] = _configuration_answer(**WITHOUT_SHACL)

    with pytest.raises(TripleStoreNotSupportedError) as refused:
        adapter.shapes_set(SHAPES, "text/turtle")

    assert f"'{DATASET}'" in str(refused.value)
    assert _requests(store) == [("GET", CONFIGURATION, None)]


def test_shapes_set_when_the_store_does_not_say_whether_it_validates_raises(
    store, adapter
):
    """Unknown is refused: the shapes would otherwise be stored as data that validate
    nothing."""
    store.answers[CONFIGURATION] = _configuration_answer(ruleset="rdfsplus-optimized")

    with pytest.raises(TripleStoreNotSupportedError):
        adapter.shapes_set(SHAPES, "text/turtle")

    assert _requests(store) == [("GET", CONFIGURATION, None)]


def test_shapes_set_raises_the_refusal_when_the_data_violates_the_new_shapes(
    store, adapter
):
    report = "_:r <http://www.w3.org/ns/shacl#conforms> false ."
    store.answers[CONFIGURATION] = _configuration_answer(**WITH_SHACL)
    store.method_answers[("PUT", GRAPH_STORE)] = answer(
        500, report, "application/shacl-validation-report+n-quads"
    )

    with pytest.raises(ShaclValidationError) as refused:
        adapter.shapes_set(SHAPES, "text/turtle")

    assert refused.value.report == report
    assert refused.value.status == 500
    # Nothing is sent after the refused replacement, so the old shapes stay.
    assert _requests(store) == [
        ("GET", CONFIGURATION, None),
        ("PUT", GRAPH_STORE, {"graph": SHAPES_GRAPH}),
    ]


@pytest.mark.parametrize(
    ("method", "path", "data"),
    [
        ("GET", CONFIGURATION, SHAPES),
        ("PUT", GRAPH_STORE, SHAPES),
        ("DELETE", GRAPH_STORE, ""),
    ],
    ids=["configuration", "replace", "remove-every-shape"],
)
def test_shapes_set_raises_an_error_answer_of_each_request_with_its_status(
    store, adapter, method, path, data
):
    store.answers[CONFIGURATION] = _configuration_answer(**WITH_SHACL)
    store.answers[GRAPH_STORE] = answer(204)
    store.method_answers[(method, path)] = answer(403, BODY)

    with pytest.raises(TripleStoreAccessError) as failed:
        adapter.shapes_set(data, "text/turtle")

    assert failed.value.status == 403
    assert str(failed.value).endswith(f"(403) - {BODY}")
    assert f"'{DATASET}'" in str(failed.value)


# -- the detection of SHACL validation, for each answer ----------------------------------------


@pytest.mark.parametrize(
    ("configuration", "expected"),
    [
        (_configuration(isShacl="true", validationEnabled="true"), True),
        (_configuration(isShacl="true"), True),
        (_configuration(isShacl=True, validationEnabled=True), True),
        (_configuration(isShacl="false", validationEnabled="true"), False),
        (_configuration(isShacl="false"), False),
        (_configuration(isShacl="true", validationEnabled="false"), False),
        (_configuration(ruleset="rdfsplus-optimized"), None),
        (_configuration(isShacl="maybe"), None),
        ({"id": DATASET}, None),
        ({"params": None}, None),
        ([], None),
        (None, None),
    ],
    ids=[
        "shacl-and-validation",
        "shacl-without-the-validation-flag",
        "shacl-as-json-booleans",
        "no-shacl",
        "no-shacl-without-the-validation-flag",
        "shacl-with-validation-off",
        "no-shacl-flag",
        "an-unknown-shacl-flag",
        "no-params",
        "params-not-an-object",
        "not-an-object",
        "nothing",
    ],
)
def test_the_detection_reads_the_shacl_flags_of_the_configuration(
    configuration, expected
):
    assert _shacl_validation_on(configuration) is expected


# -- a store without the registries ------------------------------------------------------------


class _StoreWithoutRegistries(TripleStore):
    """An adapter that inherits the contract and has neither registry."""


REGISTRY_OPERATIONS = pytest.mark.parametrize(
    "operation",
    [
        lambda db: db.prefixes_get(),
        lambda db: db.prefix_set("ex", EX),
        lambda db: db.prefix_delete("ex"),
        lambda db: db.shapes_set(SHAPES, "text/turtle"),
        lambda db: db.validate(SHAPES, "text/turtle"),
    ],
    ids=["prefixes_get", "prefix_set", "prefix_delete", "shapes_set", "validate"],
)


@REGISTRY_OPERATIONS
def test_an_adapter_without_the_registries_raises_not_supported(operation):
    """Never a silent no-op: the contract's own operations raise."""
    with pytest.raises(TripleStoreNotSupportedError) as refused:
        operation(_StoreWithoutRegistries())

    assert "_StoreWithoutRegistries" in str(refused.value)


# -- validate ----------------------------------------------------------------------------------

VALIDATE = f"/rest/repositories/{DATASET}/validate/text"
REPORT = """@prefix sh: <http://www.w3.org/ns/shacl#> .
[] a sh:ValidationReport ;
    sh:conforms false ;
    sh:result [ a sh:ValidationResult ; sh:focusNode <http://example.org/registry#item> ] .
"""


def test_validate_returns_the_recorded_report_unchanged(store, adapter):
    store.answers[VALIDATE] = answer(200, REPORT, "text/turtle")

    assert adapter.validate(SHAPES, "text/turtle") == REPORT

    assert [(m, p) for m, p, _ in store.sent] == [("POST", VALIDATE)]
    assert store.bodies == [SHAPES.encode()]
    assert store.headers[0]["Content-Type"] == "text/turtle"
    assert store.headers[0]["Accept"] == "text/turtle"


def test_validate_maps_a_404_to_an_invalid_dataset(store, adapter):
    store.answers[VALIDATE] = answer(404, BODY)

    with pytest.raises(InvalidDatasetError) as failed:
        adapter.validate(SHAPES, "text/turtle")

    assert f"'{DATASET}'" in str(failed.value)


def test_validate_maps_a_401_to_an_authentication_error(store, adapter):
    store.answers[VALIDATE] = answer(401, BODY)

    with pytest.raises(AuthenticationError) as failed:
        adapter.validate(SHAPES, "text/turtle")

    assert failed.value.status == 401


def test_validate_sends_an_empty_document_as_white_space(store, adapter):
    """GraphDB answers 400 to an empty body, so the adapter sends a newline instead."""
    store.answers[VALIDATE] = answer(200, REPORT, "text/turtle")

    assert adapter.validate("", "text/turtle") == REPORT

    assert store.bodies == [b"\n"]
