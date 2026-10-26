"""The interface sends each query that it builds for its own operations as text.

`GraphDB.query` parses a `SPARQLQuery` before it sends it: a read goes through rdflib's
`prepareQuery`, and an insert or delete runs once on an empty in-memory dataset. The interface
renders every term of its own queries itself, through the triple sanitizer and `n3()`, so that
parse could find only a defect in a fixed template. Each own operation therefore gives `query`
the text from `to_string(validate=False)`.

The store is a stand-in behind `_make_request`. A recorder around `GraphDB.query` shows what
each operation hands it, and the two validators of `utils` are replaced by counters.
"""

import pytest
import requests

import kapps_triplestore_interface.sparql_query as sparql_query_module
from kapps_triplestore_interface import GraphDB, GraphDBCredentials
from kapps_triplestore_interface.exceptions import (
    InvalidIRIError,
    InvalidQueryError,
)
from kapps_triplestore_interface.sparql_query import SPARQLQuery

GRAPH = "http://example.org/g"
SUB = "http://example.org/onto#box-1"
PRED = "http://example.org/onto#hasPart"
OBJ = "http://example.org/onto#part-1"
OTHER_OBJ = "http://example.org/onto#part-2"
TRIPLE = (SUB, PRED, OBJ)
MORE = [TRIPLE, (SUB, PRED, OTHER_OBJ)]


def _response(media_type: str, body: str) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = media_type
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


@pytest.fixture
def requests_sent() -> list:
    """The request bodies that reached the store, oldest first."""
    return []


@pytest.fixture
def client(monkeypatch, requests_sent) -> GraphDB:
    """Not named `db`: the conftest marks every test that requests `db` as live.

    Every read answers "true" with no bindings, so that an existence check passes and a
    checked write finds its receipt.
    """

    def make_request(self, method, endpoint, timeout=None, **kwargs):
        if endpoint == "rest/login":
            answer = _response("application/json", "")
            answer.headers["Authorization"] = "GDB token"
            return answer
        if endpoint == "rest/repositories":
            return _response("application/json", '[{"id": "repo"}]')
        if endpoint in ("repositories/repo", "repositories/repo/statements"):
            requests_sent.append(kwargs["data"])
            return _response(
                "application/sparql-results+json",
                '{"head": {"vars": []}, "boolean": true, '
                '"results": {"bindings": []}}',
            )
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


@pytest.fixture
def given(monkeypatch, client) -> list:
    """What each call gave `GraphDB.query`, as `(query, update)` in order."""
    calls = []
    original = GraphDB.query

    def recording_query(self, query, update=False, convert_bindings=False):
        calls.append((query, update))
        return original(self, query, update=update, convert_bindings=convert_bindings)

    monkeypatch.setattr(GraphDB, "query", recording_query)
    return calls


# Each own operation, in the form that builds a `SPARQLQuery`. The checked writes of
# `triple_delete`, `triple_update` and the multi-triple writes already send strings.
OPERATIONS = {
    "triples_get": lambda db: db.triples_get(sub=SUB, named_graph=GRAPH),
    "owl_get_classes_of_individual": lambda db: db.owl_get_classes_of_individual(
        SUB, named_graph=GRAPH
    ),
    "iri_exists": lambda db: db.iri_exists(SUB, as_sub=True, named_graph=GRAPH),
    "any_triple_exists": lambda db: db.any_triple_exists(MORE, named_graph=GRAPH),
    "all_triple_exists": lambda db: db.all_triple_exists(MORE, named_graph=GRAPH),
    "triple_exists": lambda db: db.triple_exists(TRIPLE, named_graph=GRAPH),
    "triples_add": lambda db: db.triples_add(MORE, check_exist=False, named_graph=GRAPH),
    "triples_delete": lambda db: db.triples_delete(
        MORE, check_exist=False, named_graph=GRAPH
    ),
    "triple_add": lambda db: db.triple_add(TRIPLE, named_graph=GRAPH),
    "triple_delete": lambda db: db.triple_delete(
        TRIPLE, check_exist=False, named_graph=GRAPH
    ),
    "triple_update": lambda db: db.triple_update(
        TRIPLE, new_obj=OTHER_OBJ, check_exist=False, named_graph=GRAPH
    ),
}

# The same operations in their checked form, where they have one.
CHECKED_OPERATIONS = {
    "triples_add": lambda db: db.triples_add(MORE, named_graph=GRAPH),
    "triples_delete": lambda db: db.triples_delete(MORE, named_graph=GRAPH),
    "triple_delete": lambda db: db.triple_delete(TRIPLE, named_graph=GRAPH),
    "triple_update": lambda db: db.triple_update(
        TRIPLE, new_obj=OTHER_OBJ, named_graph=GRAPH
    ),
}


@pytest.fixture
def validators(monkeypatch) -> list:
    """The calls of the interface's query validation and update validation."""
    calls = []
    for name in ("validate_query", "validate_update_query"):
        original = getattr(sparql_query_module.utils, name)

        def counting(query, _name=name, _original=original):
            calls.append(_name)
            return _original(query)

        monkeypatch.setattr(sparql_query_module.utils, name, counting)
    return calls


@pytest.mark.parametrize("name", OPERATIONS)
def test_an_own_operation_gives_query_text(name, client, given):
    OPERATIONS[name](client)
    assert given, f"{name} sent no query"
    built = [query for query, _ in given if not isinstance(query, str)]
    assert built == [], f"{name} gave query a SPARQLQuery"


@pytest.mark.parametrize("name", CHECKED_OPERATIONS)
def test_a_checked_write_gives_query_text(name, client, given):
    CHECKED_OPERATIONS[name](client)
    assert given, f"{name} sent no query"
    assert all(isinstance(query, str) for query, _ in given)


@pytest.mark.parametrize("name", OPERATIONS)
def test_an_own_operation_does_not_validate(name, client, validators):
    OPERATIONS[name](client)
    assert validators == []


@pytest.mark.parametrize("name", CHECKED_OPERATIONS)
def test_a_checked_write_does_not_validate(name, client, validators):
    CHECKED_OPERATIONS[name](client)
    assert validators == []


@pytest.mark.parametrize("name", OPERATIONS)
def test_an_own_operation_sends_the_text_that_the_validated_rendering_gives(
    name, monkeypatch, client, requests_sent
):
    """The text on the wire is the text that `to_string()` renders and validates."""
    rendered = []
    original = SPARQLQuery.to_string

    def recording(self, validate=True):
        text = original(self, validate=validate)
        rendered.append((self, text))
        return text

    monkeypatch.setattr(SPARQLQuery, "to_string", recording)
    OPERATIONS[name](client)
    assert len(requests_sent) == len(rendered) == 1
    query, text = rendered[0]
    assert requests_sent == [text]
    # The validated rendering of the same query is the same text.
    assert original(query, validate=True) == text


def test_a_malformed_query_of_a_caller_is_still_refused(client, requests_sent):
    query = SPARQLQuery.select(variables=["?s"], where_clauses=["?s ?p"])
    with pytest.raises(InvalidQueryError):
        client.query(query)
    assert requests_sent == []


def test_a_malformed_update_of_a_caller_is_still_refused(client, requests_sent):
    query = SPARQLQuery.insert_data(
        triples=[("http://example.org/a", "http://example.org/b", 1)]
    )
    query._query_blocks[-1]["data"] += " garbage"
    with pytest.raises(InvalidQueryError):
        client.query(query, update=True)
    assert requests_sent == []


def test_a_string_of_a_caller_is_sent_without_a_parse(client, validators, requests_sent):
    text = "this is not SPARQL"
    client.query(text)
    assert requests_sent == [text]
    assert validators == []


@pytest.mark.parametrize("name", OPERATIONS)
def test_a_malformed_iri_fails_before_any_request(
    name, client, requests_sent
):
    calls = {
        "triples_get": lambda db: db.triples_get(sub="not an iri"),
        "owl_get_classes_of_individual": lambda db: db.owl_get_classes_of_individual(
            "not an iri"
        ),
        "iri_exists": lambda db: db.iri_exists("not an iri", as_sub=True),
        "any_triple_exists": lambda db: db.any_triple_exists([("not an iri", PRED, OBJ)]),
        "all_triple_exists": lambda db: db.all_triple_exists([("not an iri", PRED, OBJ)]),
        "triple_exists": lambda db: db.triple_exists(("not an iri", PRED, OBJ)),
        "triples_add": lambda db: db.triples_add(
            [("not an iri", PRED, OBJ)], check_exist=False
        ),
        "triples_delete": lambda db: db.triples_delete(
            [("not an iri", PRED, OBJ)], check_exist=False
        ),
        "triple_add": lambda db: db.triple_add(("not an iri", PRED, OBJ)),
        "triple_delete": lambda db: db.triple_delete(
            ("not an iri", PRED, OBJ), check_exist=False
        ),
        "triple_update": lambda db: db.triple_update(
            ("not an iri", PRED, OBJ), new_obj=OTHER_OBJ, check_exist=False
        ),
    }
    before = len(requests_sent)
    with pytest.raises(InvalidIRIError):
        calls[name](client)
    assert len(requests_sent) == before
