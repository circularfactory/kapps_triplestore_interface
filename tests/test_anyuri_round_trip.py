"""A literal with an explicit datatype, written, read back, updated and removed, without a store.

A URL-valued property, for example the address of a service, stores its value as an
`xsd:anyURI` literal. The write must keep that datatype. The read must give back the same
typed literal, so that a later update or removal names the triple that the store holds.

The typed writers below do what an object-graph mapper does: they read the stored value, and
they pass the old and the new value through `to_literal`. The store is an in-memory rdflib
dataset behind the client's HTTP layer, so `GraphDB.query` and its conversion of the bindings
run as they do against GraphDB.
"""

import pytest
import requests
import rdflib.plugins.sparql
from rdflib import Dataset, Literal, URIRef, XSD

from kapps_triplestore_interface import GraphDB, GraphDBCredentials, to_literal
from kapps_triplestore_interface.utils import utils

GRAPH = URIRef("http://example.org/services")
SERVICE = URIRef("http://example.org/services#detector")
ADDRESS = URIRef("http://example.org/ontology#address")

WITH_SLASH = "http://h:1/"
WITHOUT_SLASH = "http://h:1"
MQTT = "mqtt://broker:1883"


def _any_uri(value: str) -> Literal:
    return Literal(value, datatype=XSD.anyURI)


def _response(status: int, media_type: str, body: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = media_type
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


@pytest.fixture
def store(monkeypatch) -> Dataset:
    """The in-memory dataset that answers the client's requests."""
    # A `FROM <g>` reads the dataset's own graph, instead of fetching `<g>` from the web.
    monkeypatch.setattr(rdflib.plugins.sparql, "SPARQL_LOAD_GRAPHS", False)
    return Dataset()


@pytest.fixture
def client(monkeypatch, store) -> GraphDB:
    """A client whose requests the dataset answers. Nothing reaches a network.

    Not named `db`: the conftest marks every test that requests `db` as live.
    """

    def make_request(self, method, endpoint, timeout=None, **kwargs):
        if endpoint == "rest/login":
            answer = _response(200, "application/json", "")
            answer.headers["Authorization"] = "GDB token"
            return answer
        if endpoint == "rest/repositories":
            return _response(200, "application/json", '[{"id": "repo"}]')
        if endpoint == "repositories/repo/statements":
            store.update(kwargs["data"])
            return _response(204, "text/plain", "")
        if endpoint == "repositories/repo":
            result = store.query(kwargs["data"]).serialize(format="json")
            return _response(200, "application/sparql-results+json", result.decode())
        raise AssertionError(f"unexpected request: {method} {endpoint}")

    monkeypatch.setattr(GraphDB, "_make_request", make_request)
    return GraphDB(
        GraphDBCredentials(
            base_url="http://example.org",
            username="user",
            password="password",
            repository="repo",
        )
    )


def _stored(store: Dataset) -> set:
    return set(store.graph(GRAPH).objects(SERVICE, ADDRESS))


def _read(client: GraphDB):
    [(_, _, value)] = client.triples_get(sub=SERVICE, pred=ADDRESS, named_graph=GRAPH)
    return value


# --- the write ---------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [WITH_SLASH, MQTT], ids=["http", "mqtt"])
def test_a_literal_keeps_its_explicit_datatype(value):
    assert to_literal(_any_uri(value)) == _any_uri(value)


@pytest.mark.parametrize(
    "value", ["Hello", Literal("Hello")], ids=["str", "literal-without-datatype"]
)
def test_a_plain_string_is_written_as_xsd_string(value):
    assert to_literal(value) == Literal("Hello", datatype=XSD.string)


def test_a_datatype_argument_replaces_the_literals_own():
    assert to_literal(_any_uri(WITH_SLASH), datatype=XSD.string) == Literal(
        WITH_SLASH, datatype=XSD.string
    )


# --- the read ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [WITH_SLASH, WITHOUT_SLASH, MQTT],
    ids=["trailing-slash", "no-trailing-slash", "mqtt"],
)
def test_an_any_uri_value_reads_back_as_the_typed_literal(value):
    binding = {"type": "literal", "value": value, "datatype": str(XSD.anyURI)}
    converted = utils.convert_binding_to_python_type(binding)
    assert isinstance(converted, Literal)
    assert converted == _any_uri(value)
    assert str(converted) == value


@pytest.mark.parametrize("value", [WITH_SLASH, MQTT], ids=["http", "mqtt"])
def test_a_stored_any_uri_value_reads_back_through_the_client(client, store, value):
    store.add((SERVICE, ADDRESS, _any_uri(value), GRAPH))
    assert _read(client) == _any_uri(value)


# --- typed writers -----------------------------------------------------------------------------


def test_a_typed_writer_re_addresses_a_value(client, store):
    store.add((SERVICE, ADDRESS, _any_uri(WITH_SLASH), GRAPH))

    client.triples_update(
        [(SERVICE, ADDRESS, to_literal(_read(client)))],
        [(SERVICE, ADDRESS, to_literal(_any_uri("http://h:2/")))],
        named_graph=GRAPH,
    )

    assert _stored(store) == {_any_uri("http://h:2/")}


def test_a_typed_writer_removes_a_value(client, store):
    store.add((SERVICE, ADDRESS, _any_uri(WITH_SLASH), GRAPH))

    client.triples_delete(
        [(SERVICE, ADDRESS, to_literal(_read(client)))], named_graph=GRAPH
    )

    assert _stored(store) == set()


def test_a_typed_writer_writes_an_mqtt_value(client, store):
    client.triples_add(
        [(SERVICE, ADDRESS, to_literal(_any_uri(MQTT)))], named_graph=GRAPH
    )

    assert _stored(store) == {_any_uri(MQTT)}
    assert _read(client) == _any_uri(MQTT)


def test_a_typed_writer_replaces_a_legacy_string_value(client, store):
    # A writer that passed a plain string stored it as xsd:string.
    store.add((SERVICE, ADDRESS, Literal(WITH_SLASH, datatype=XSD.string), GRAPH))

    client.triples_update(
        [(SERVICE, ADDRESS, to_literal(_read(client)))],
        [(SERVICE, ADDRESS, to_literal(_any_uri(WITH_SLASH)))],
        named_graph=GRAPH,
    )

    assert _stored(store) == {_any_uri(WITH_SLASH)}
