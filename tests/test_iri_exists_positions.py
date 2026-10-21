"""`iri_exists` with several positions: the positions are alternatives, not a join.

The store is an in-memory rdflib dataset behind the client's HTTP layer, as in the anyURI
round-trip test. Both scope flags stay at their defaults: the explicit-only scope is a GraphDB
graph that rdflib lacks.
"""

import itertools

import pytest
import requests
import rdflib.plugins.sparql
from rdflib import Dataset, URIRef, RDF

from kapps_triplestore_interface import GraphDB, GraphDBCredentials
from kapps_triplestore_interface.exceptions import InvalidInputError
from kapps_triplestore_interface.sparql_query import SPARQLQuery
from kapps_triplestore_interface.utils.iri import IRI

GRAPH = URIRef("http://example.org/g")
OTHER_GRAPH = URIRef("http://example.org/other")
INSTANCE = URIRef("http://example.org/onto#box-1")
CLASS = URIRef("http://example.org/onto#Box")
ELSEWHERE = URIRef("http://example.org/onto#box-2")

ALL = {"as_sub": True, "as_pred": True, "as_obj": True}
NAMES = ("as_sub", "as_pred", "as_obj")
EVERY_CHOICE = [
    {name: True for name in chosen}
    for size in (1, 2, 3)
    for chosen in itertools.combinations(NAMES, size)
]


def _response(status: int, media_type: str, body: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = media_type
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


@pytest.fixture
def store(monkeypatch) -> Dataset:
    monkeypatch.setattr(rdflib.plugins.sparql, "SPARQL_LOAD_GRAPHS", False)
    dataset = Dataset()
    dataset.graph(GRAPH).add((INSTANCE, RDF.type, CLASS))
    dataset.graph(OTHER_GRAPH).add((ELSEWHERE, RDF.type, CLASS))
    return dataset


@pytest.fixture
def sent() -> list:
    """The queries that reached the store, oldest first."""
    return []


@pytest.fixture
def client(monkeypatch, store, sent) -> GraphDB:
    """Not named `db`: the conftest marks every test that requests `db` as live."""

    def make_request(self, method, endpoint, timeout=None, **kwargs):
        if endpoint == "rest/login":
            answer = _response(200, "application/json", "")
            answer.headers["Authorization"] = "GDB token"
            return answer
        if endpoint == "rest/repositories":
            return _response(200, "application/json", '[{"id": "repo"}]')
        if endpoint == "repositories/repo":
            sent.append(kwargs["data"])
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


def _asked(iri, client, **positions) -> bool:
    return client.iri_exists(iri, named_graph=GRAPH, **positions)


def test_an_instance_that_is_only_a_subject_is_found_for_all_three_positions(client):
    assert _asked(INSTANCE, client, **ALL) is True


@pytest.mark.parametrize(
    "positions, expected",
    [
        ({"as_sub": True}, True),
        ({"as_pred": True}, False),
        ({"as_obj": True}, False),
        ({"as_sub": True, "as_pred": True}, True),
        ({"as_pred": True, "as_obj": True}, False),
    ],
)
def test_the_instance_is_found_only_in_the_positions_it_holds(
    client, positions, expected
):
    assert _asked(INSTANCE, client, **positions) is expected


@pytest.mark.parametrize(
    "positions",
    [{"as_sub": True}, {"as_obj": True}, {"as_sub": True, "as_obj": True}, ALL],
)
def test_a_class_that_is_only_an_object_is_found_whenever_the_object_position_is_asked(
    client, positions
):
    assert _asked(CLASS, client, **positions) is positions.get("as_obj", False)


@pytest.mark.parametrize("positions", EVERY_CHOICE)
def test_an_iri_known_only_in_another_graph_is_not_found(client, positions):
    assert _asked(ELSEWHERE, client, **positions) is False


def test_a_predicate_is_found_as_predicate_and_for_all_three_positions(client, store):
    store.graph(GRAPH).add((INSTANCE, ELSEWHERE, CLASS))
    assert _asked(ELSEWHERE, client, as_pred=True) is True
    assert _asked(ELSEWHERE, client, **ALL) is True


@pytest.mark.parametrize(
    "position, pattern",
    [
        ("as_sub", f"{{<{INSTANCE}> ?p ?o . }}"),
        ("as_pred", f"{{?s <{INSTANCE}> ?o . }}"),
        ("as_obj", f"{{?s ?p <{INSTANCE}> . }}"),
    ],
)
def test_one_position_sends_the_same_query_as_before(client, sent, position, pattern):
    _asked(INSTANCE, client, **{position: True})
    before = SPARQLQuery.ask(
        where_clauses=[pattern],
        named_graph=IRI(GRAPH),
        include_explicit=True,
        include_implicit=True,
    )
    assert sent[-1] == before.to_string()


def test_several_positions_send_alternatives_in_one_graph_block(client, sent):
    _asked(INSTANCE, client, **ALL)
    assert sent[-1].count("UNION") == 2
    assert sent[-1].count("GRAPH") == 1


def test_a_read_without_a_position_is_refused(client):
    with pytest.raises(InvalidInputError):
        client.iri_exists(INSTANCE, named_graph=GRAPH)
