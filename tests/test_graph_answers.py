"""A CONSTRUCT or DESCRIBE read through `query()` returns its triples as an rdflib `Graph`.

These tests run without a triple store: the stub in `_stub_store.py` answers as GraphDB's
content negotiation does. The client offers the JSON result format and N-Triples, and reads the
answer by its media type; it reads nothing from the query text. A SELECT and an ASK answer as
before.
"""

from __future__ import annotations

import json
import logging

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import XSD

from kapps_triplestore_interface import (
    SPARQLQuery,
    TripleStoreEndpoint,
    TripleStoreResponseError,
    connect,
    connect_kadi,
)
from kapps_triplestore_interface.auth import BasicAuth
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    GRAPH_ANSWER,
    N_TRIPLES,
    PASSWORD,
    USERNAME,
    answer,
    store,
)

ENDPOINT = TripleStoreEndpoint(url=BASE_URL, dataset=DATASET)
QUERY_PATH = f"/repositories/{DATASET}"
EX = "http://example.org/"

PROLOGUE = (
    "# an export of the test graph\n"
    f"BASE <{EX}>\n"
    "PREFIX ex: <http://example.org/#>\n"
    "PREFIX : <http://example.org/>\n"
)
CONSTRUCT = "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"
DESCRIBE = "DESCRIBE <http://example.org/s>"
SELECT = "SELECT ?s WHERE { ?s ?p ?o }"
ASK = "ASK { ?s ?p ?o }"


def _expected() -> Graph:
    graph = Graph()
    graph.add((URIRef(EX + "s"), URIRef(EX + "p"), URIRef(EX + "o")))
    graph.add((URIRef(EX + "s"), URIRef(EX + "label"), Literal("Grüße", lang="de")))
    graph.add((BNode(), URIRef(EX + "count"), Literal("7", datatype=XSD.integer)))
    return graph


@pytest.fixture(name="client")
def fixture_client(store):  # pylint: disable=redefined-outer-name
    return connect(ENDPOINT, BasicAuth(USERNAME, PASSWORD))


def _query_headers(stub) -> dict[str, str]:
    return [
        h for (_, path, _), h in zip(stub.sent, stub.headers) if path == QUERY_PATH
    ][-1]


# -- what a caller gets back ---------------------------------------------------------------------


@pytest.mark.parametrize("text", [CONSTRUCT, DESCRIBE], ids=["construct", "describe"])
def test_a_text_graph_query_returns_its_triples_as_a_graph(client, text):
    result = client.query(text)

    assert isinstance(result, Graph)
    assert isomorphic(result, _expected())


@pytest.mark.parametrize("text", [CONSTRUCT, DESCRIBE], ids=["construct", "describe"])
def test_a_graph_query_after_a_prologue_returns_a_graph(client, text):
    result = client.query(PROLOGUE + text)

    assert isinstance(result, Graph)
    assert isomorphic(result, _expected())


def test_a_select_after_a_prologue_returns_the_json_result_as_before(client, store):
    rows = {"head": {"vars": ["s"]}, "results": {"bindings": []}}
    store.answers[QUERY_PATH] = answer(
        200, json.dumps(rows), "application/sparql-results+json"
    )

    assert client.query(PROLOGUE + SELECT) == rows


def test_an_ask_after_a_prologue_returns_the_boolean_dict_as_before(client):
    assert client.query(PROLOGUE + ASK) == {"head": {}, "boolean": True}


@pytest.mark.parametrize(
    "built",
    [
        SPARQLQuery.construct(["?s ?p ?o ."], ["?s ?p ?o ."]),
        SPARQLQuery.describe(["<http://example.org/s>"]),
    ],
    ids=["construct", "describe"],
)
def test_a_built_graph_query_returns_a_graph(client, store, built):
    result = client.query(built)

    assert isinstance(result, Graph)
    assert isomorphic(result, _expected())
    assert store.bodies[-1] == built.to_string()


def test_convert_bindings_is_ignored_for_a_graph_query(client):
    result = client.query(CONSTRUCT, convert_bindings=True)

    assert isinstance(result, Graph)
    assert isomorphic(result, _expected())


def test_a_graph_answer_with_a_charset_parameter_is_read_as_a_graph(client, store):
    store.answers[QUERY_PATH] = answer(
        200, GRAPH_ANSWER, "application/n-triples; charset=UTF-8"
    )

    assert isomorphic(client.query(CONSTRUCT), _expected())


def test_a_turtle_answer_is_read_as_a_graph(client, store):
    turtle = (
        "@prefix ex: <http://example.org/> .\n"
        'ex:s ex:p ex:o ; ex:label "Grüße"@de .\n'
        "[] ex:count 7 .\n"
    )
    turtle_answer = answer(200, turtle, "text/turtle")
    turtle_answer.encoding = "ISO-8859-1"
    store.answers[QUERY_PATH] = turtle_answer

    assert isomorphic(client.query(CONSTRUCT), _expected())


def test_an_unreadable_graph_answer_raises_a_response_error(client, store):
    store.answers[QUERY_PATH] = answer(200, "<http://example.org/s> broken", N_TRIPLES)

    with pytest.raises(TripleStoreResponseError):
        client.query(CONSTRUCT)


# -- what the client sends -----------------------------------------------------------------------


def test_a_read_offers_the_json_result_format_and_n_triples(client, store):
    client.query(SELECT)

    offered = [
        media.split(";")[0].strip()
        for media in _query_headers(store)["Accept"].split(",")
    ]
    assert offered[0] == "application/sparql-results+json"
    assert N_TRIPLES in offered


def test_the_query_text_is_sent_as_it_is(client, store):
    client.query(PROLOGUE + CONSTRUCT)

    assert store.bodies[-1] == PROLOGUE + CONSTRUCT


def test_an_update_sends_the_headers_it_sent_before(client, store):
    store.answers[f"{QUERY_PATH}/statements"] = answer(204)

    client.query("INSERT DATA { <a:b> <a:c> <a:d> }", update=True)

    sent = store.headers[-1]
    assert sent["Content-Type"] == "application/sparql-update"
    assert sent["Accept"] == "application/sparql-results+json"


def test_a_kadi_read_keeps_the_json_only_offer(store):
    name = "my-repository"
    api = "/api/triple-store"
    store.answers[api] = answer(200, json.dumps({"name": name}), "application/json")
    connected = connect_kadi(host=BASE_URL, pat="pat_not-a-real-token")

    connected.query(ASK)

    assert store.headers[-1]["Accept"] == "application/sparql-results+json"


# -- the log -------------------------------------------------------------------------------------


def test_at_debug_a_graph_query_logs_the_query_and_the_triples(client, caplog):
    caplog.set_level(logging.DEBUG, logger=client.logger.name)

    client.query(CONSTRUCT)

    line = caplog.records[-1].getMessage()
    assert CONSTRUCT in line
    assert "Grüße" in line
