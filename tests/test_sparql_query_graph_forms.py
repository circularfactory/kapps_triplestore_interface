"""The CONSTRUCT and DESCRIBE builders of `SPARQLQuery` render the text a caller would write.

Like the SELECT builder, each puts the named graph and the explicit/implicit choice in `FROM`
clauses, and `to_string()` parses the text, so that an invalid built query raises
`InvalidQueryError`. These tests run without a triple store.
"""

from __future__ import annotations

import pytest

from kapps_triplestore_interface import IRI, SPARQLQuery
from kapps_triplestore_interface.exceptions import InvalidQueryError
from kapps_triplestore_interface.sparql_query import SPARQLQueryType

GRAPH = "http://example.org/graph"
EXPLICIT = "FROM <http://www.ontotext.com/explicit>"
IMPLICIT = "FROM <http://www.ontotext.com/implicit>"


# -- CONSTRUCT -----------------------------------------------------------------------------------


def test_a_construct_renders_its_template_and_its_where_clauses():
    query = SPARQLQuery.construct(
        ["?s <http://example.org/p> ?o ."], ["?s <http://example.org/q> ?o ."]
    )

    assert query.to_string() == (
        "CONSTRUCT {?s <http://example.org/p> ?o .}\n"
        "WHERE {?s <http://example.org/q> ?o .}"
    )


def test_a_construct_reads_from_the_named_graph():
    text = SPARQLQuery.construct(
        ["?s ?p ?o ."], ["?s ?p ?o ."], named_graph=GRAPH
    ).to_string()

    assert text == f"CONSTRUCT {{?s ?p ?o .}}\nFROM <{GRAPH}>\nWHERE {{?s ?p ?o .}}"


@pytest.mark.parametrize(
    "explicit, implicit, clause",
    [(True, False, EXPLICIT), (False, True, IMPLICIT), (True, True, None)],
)
def test_a_construct_honours_explicit_and_implicit(explicit, implicit, clause):
    text = SPARQLQuery.construct(
        ["?s ?p ?o ."],
        ["?s ?p ?o ."],
        include_explicit=explicit,
        include_implicit=implicit,
    ).to_string()

    if clause is None:
        assert "FROM" not in text
    else:
        assert text.splitlines()[1] == clause


def test_a_construct_names_the_graph_before_the_inference_choice_as_select_does():
    construct = SPARQLQuery.construct(
        ["?s ?p ?o ."], ["?s ?p ?o ."], named_graph=GRAPH, include_implicit=False
    ).to_string()
    select = SPARQLQuery.select(
        ["?s"], ["?s ?p ?o ."], named_graph=GRAPH, include_implicit=False
    ).to_string()

    assert construct.splitlines()[1:3] == select.splitlines()[1:3]
    assert construct.splitlines()[1:3] == [f"FROM <{GRAPH}>", EXPLICIT]


def test_an_invalid_construct_raises_invalid_query_error():
    with pytest.raises(InvalidQueryError):
        SPARQLQuery.construct(["?s ?p ."], ["?s ?p ?o ."]).to_string()


def test_a_construct_block_has_the_construct_type():
    query = SPARQLQuery()
    query.add_construct_block(["?s ?p ?o ."], ["?s ?p ?o ."])

    assert query._query_blocks[0]["type"] is SPARQLQueryType.CONSTRUCT


# -- DESCRIBE ------------------------------------------------------------------------------------


def test_a_describe_of_a_resource_needs_no_where_clause():
    text = SPARQLQuery.describe(["<http://example.org/s>"]).to_string()

    assert text == "DESCRIBE <http://example.org/s>"


def test_a_describe_renders_an_iri_and_a_variable_with_where_clauses():
    text = SPARQLQuery.describe(
        [IRI("http://example.org/s"), "?x"], ["?x <http://example.org/p> ?y ."]
    ).to_string()

    assert text == (
        "DESCRIBE <http://example.org/s> ?x\n" "WHERE {?x <http://example.org/p> ?y .}"
    )


def test_a_describe_reads_from_the_named_graph_and_honours_explicit_only():
    text = SPARQLQuery.describe(
        ["?x"],
        ["?x ?p ?o ."],
        named_graph=GRAPH,
        include_implicit=False,
    ).to_string()

    assert text.splitlines() == [
        "DESCRIBE ?x",
        f"FROM <{GRAPH}>",
        EXPLICIT,
        "WHERE {?x ?p ?o .}",
    ]


def test_a_describe_honours_implicit_only():
    text = SPARQLQuery.describe(
        ["<http://example.org/s>"], include_explicit=False
    ).to_string()

    assert text.splitlines() == ["DESCRIBE <http://example.org/s>", IMPLICIT]


def test_an_invalid_describe_raises_invalid_query_error():
    with pytest.raises(InvalidQueryError):
        SPARQLQuery.describe(["?x"], ["?x ?p"]).to_string()


def test_a_describe_of_nothing_raises_invalid_query_error():
    with pytest.raises(InvalidQueryError):
        SPARQLQuery.describe([], ["?x ?p ?o ."])


def test_a_describe_block_has_the_describe_type():
    query = SPARQLQuery()
    query.add_describe_block(["?x"], ["?x ?p ?o ."])

    assert query._query_blocks[0]["type"] is SPARQLQueryType.DESCRIBE
