"""`IRI` accepts `urn:` IRIs, so a leftover write receipt does not break converted reads.

The checked write mints `urn:uuid:<uuid4>` receipts, with the predicate `urn:x-kapps:appliedAt`
in the graph `urn:x-kapps:write-receipts`. A receipt stays behind when a process dies. These
tests use recorded store answers; the live half is in `test_urn_receipt_live.py`.
"""

import json
from uuid import uuid4

import pytest
import requests

from kapps_triplestore_interface import GraphDB, GraphDBCredentials, IRI
from kapps_triplestore_interface.exceptions import InvalidIRIError
from kapps_triplestore_interface.queries.checked_write import (
    RECEIPT_GRAPH,
    RECEIPT_PREDICATE,
)
from kapps_triplestore_interface.utils import utils
from kapps_triplestore_interface.utils.pretty_print import shorten_block

RECEIPT = f"urn:uuid:{uuid4()}"
URN_IRIS = [
    RECEIPT,
    "urn:x-kapps:appliedAt",
    "urn:x-kapps:write-receipts",
    "urn:uuid:generated-blank-instance",
]


@pytest.mark.parametrize("text", URN_IRIS)
def test_a_urn_iri_is_accepted_and_equals_its_input(text):
    assert str(IRI(text)) == text
    assert IRI(text) == text


def test_the_receipt_names_of_the_checked_write_are_valid():
    assert IRI(str(RECEIPT_GRAPH)) == "urn:x-kapps:write-receipts"
    assert IRI(str(RECEIPT_PREDICATE)) == "urn:x-kapps:appliedAt"


def test_angle_brackets_and_trailing_separators_are_trimmed_as_for_every_input():
    assert IRI("<urn:x-kapps:appliedAt>") == IRI("urn:x-kapps:appliedAt")
    assert str(IRI("<urn:x-kapps:appliedAt>")) == "urn:x-kapps:appliedAt"
    assert str(IRI("urn:x-kapps:appliedAt#")) == "urn:x-kapps:appliedAt"


def test_the_nss_can_hold_more_colons_and_one_hash():
    assert str(IRI("urn:isbn:a:b:c")) == "urn:isbn:a:b:c"
    assert str(IRI("urn:example:thing#part")) == "urn:example:thing#part"


def test_the_nid_can_be_two_to_thirty_two_characters():
    assert str(IRI("urn:ab:x")) == "urn:ab:x"
    nid32 = "a" * 32
    assert str(IRI(f"urn:{nid32}:x")) == f"urn:{nid32}:x"
    with pytest.raises(InvalidIRIError):
        IRI(f"urn:{'a' * 33}:x")
    with pytest.raises(InvalidIRIError):
        IRI("urn:a:x")


@pytest.mark.parametrize(
    "text",
    [
        "urn:",
        "urn:uuid",
        "urn:uuid:",
        "urn::abc",
        "urn:-x:abc",
        "urn:x-:abc",
        "urn:x_y:abc",
        "urn:x-kapps:a#b#c",
        "urn:x-kapps:a b",
        "URN:uuid:abc",
    ],
)
def test_malformed_urns_raise(text):
    with pytest.raises(InvalidIRIError):
        IRI(text)


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("http://example.org/owl:Class", "':' outside of supported schemes"),
        ("owl#Class", "malformed format"),
        ("unknown:Class", "unknown prefix"),
        ("a:b:c", "multiple ':' separators"),
        ("mailto:someone@example.org", "unknown prefix"),
    ],
)
def test_other_inputs_keep_their_refusals(text, fragment):
    with pytest.raises(InvalidIRIError, match=fragment):
        IRI(text)


def test_a_receipt_has_the_whole_iri_as_onto_and_local_name():
    iri = IRI(RECEIPT)
    assert iri.onto == RECEIPT
    assert utils.get_local_name(RECEIPT) == RECEIPT


def test_short_still_raises_for_an_iri_without_a_hash():
    with pytest.raises(ValueError):
        IRI(RECEIPT).short


def test_the_pretty_print_keeps_a_quoted_receipt_unchanged():
    text = f'subject "{RECEIPT}" done'
    assert shorten_block(text) == text


# -- recorded store answers ---------------------------------------------------------------


def _response(status: int, media_type: str | None, body: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    if media_type is not None:
        response.headers["Content-Type"] = media_type
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


def _binding(value: str) -> dict:
    return {"type": "uri", "value": value}


@pytest.fixture
def store(monkeypatch):
    """A client whose store answers a SELECT with `answer_to_select` and a clear with 204."""
    sent: list = []
    state = {"select": None}

    def make_request(self, method, endpoint, timeout=None, **kwargs):
        if endpoint == "rest/login":
            answer = _response(200, "application/json", "")
            answer.headers["Authorization"] = "GDB token"
            return answer
        if endpoint == "rest/repositories":
            return _response(200, "application/json", '[{"id": "repo"}]')
        sent.append((method, endpoint, kwargs.get("params")))
        if method == "delete":
            return _response(204, None, "")
        return _response(200, "application/sparql-results+json", state["select"])

    monkeypatch.setattr(GraphDB, "_make_request", make_request)
    client = GraphDB(
        GraphDBCredentials(
            base_url="http://example.org",
            username="user",
            password="password",
            repository="repo",
        )
    )
    return client, sent, state


def test_a_converted_query_returns_a_receipt_its_predicate_and_graph_as_iris(store):
    db, _, state = store
    state["select"] = json.dumps(
        {
            "head": {"vars": ["s", "p", "o", "g"]},
            "results": {
                "bindings": [
                    {
                        "s": _binding(RECEIPT),
                        "p": _binding("urn:x-kapps:appliedAt"),
                        "o": {
                            "type": "literal",
                            "value": "2026-10-11T10:00:00Z",
                            "datatype": "http://www.w3.org/2001/XMLSchema#dateTime",
                        },
                        "g": _binding("urn:x-kapps:write-receipts"),
                    }
                ]
            },
        }
    )

    row = db.query("SELECT * WHERE { GRAPH ?g { ?s ?p ?o } }", convert_bindings=True)[
        "results"
    ]["bindings"][0]

    assert isinstance(row["s"], IRI) and row["s"] == RECEIPT
    assert isinstance(row["p"], IRI) and row["p"] == "urn:x-kapps:appliedAt"
    assert isinstance(row["g"], IRI) and row["g"] == "urn:x-kapps:write-receipts"


def test_graphs_get_lists_the_receipt_graph(store):
    db, _, state = store
    state["select"] = json.dumps(
        {
            "head": {"vars": ["graph"]},
            "results": {
                "bindings": [
                    {"graph": _binding("urn:x-kapps:write-receipts")},
                    {"graph": _binding("http://example.org/g")},
                ]
            },
        }
    )

    graphs = db.graphs_get()

    assert graphs == ["urn:x-kapps:write-receipts", "http://example.org/g"]
    assert all(isinstance(graph, IRI) for graph in graphs)


def test_graph_clear_of_the_receipt_graph_sends_one_delete_naming_it(store):
    db, sent, _ = store

    assert db.graph_clear("urn:x-kapps:write-receipts") is True

    assert sent == [
        (
            "delete",
            "repositories/repo/rdf-graphs/service",
            {"graph": "urn:x-kapps:write-receipts"},
        )
    ]


def test_the_deprecated_clear_graph_clears_the_receipt_graph_too(store):
    db, sent, _ = store

    with pytest.warns(DeprecationWarning):
        assert db.clear_graph("urn:x-kapps:write-receipts") is True

    assert [params for _, _, params in sent] == [
        {"graph": "urn:x-kapps:write-receipts"}
    ]


def test_a_registered_prefix_named_urn_keeps_the_prefix_reading():
    assert str(IRI("urn:Thing", prefixes={"urn": "http://example.org/u"})) == (
        "http://example.org/u#Thing"
    )


@pytest.mark.parametrize("character", list('<>"{}|\\^`'))
def test_the_nss_refuses_characters_that_no_iri_can_hold(character):
    with pytest.raises(InvalidIRIError):
        IRI(f"urn:ab:x{character}y")
