"""Live tests: a CONSTRUCT or DESCRIBE through `query()` returns the store's triples as a graph.

The store answers a read by content negotiation: the client offers the JSON result format and
N-Triples, and these tests show that GraphDB answers a CONSTRUCT and a DESCRIBE in N-Triples
and a SELECT and an ASK in JSON, also after a prologue.

Each test seeds one named graph and clears it after. Its predicates lie outside the RDFS and
OWL vocabularies, so that the ruleset infers nothing into the graph, and the queries read the
named graph alone, so that the default graph's inferred statements stay out.
"""

from __future__ import annotations

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import XSD

from kapps_triplestore_interface import GraphDB, SPARQLQuery

EX = "http://example.org/graph_answers#"
GRAPH = "http://example.org/graph_answers_graph"
S = URIRef(EX + "s")
ITEMS = 5

PROLOGUE = f"# a prologue\nPREFIX ex: <{EX}>\nPREFIX g: <http://example.org/#>\n"


def _seed() -> Graph:
    """What the tests write: IRIs, a typed and a language-tagged literal, a blank node."""
    seed = Graph()
    seed.add((S, URIRef(EX + "p"), URIRef(EX + "o")))
    seed.add((S, URIRef(EX + "label"), Literal("Grüße", lang="de")))
    seed.add((S, URIRef(EX + "count"), Literal("7", datatype=XSD.integer)))
    node = BNode()
    seed.add((node, URIRef(EX + "note"), Literal("an anonymous note")))
    seed.add((node, URIRef(EX + "about"), URIRef(EX + "o")))
    for rank in range(ITEMS):
        seed.add(
            (
                URIRef(f"{EX}item{rank}"),
                URIRef(EX + "rank"),
                Literal(rank, datatype=XSD.integer),
            )
        )
    return seed


def _about_s(seed: Graph) -> Graph:
    """The description of `S`: it is only ever a subject, and its objects are no blank node."""
    about = Graph()
    for triple in seed.triples((S, None, None)):
        about.add(triple)
    return about


@pytest.fixture(name="seeded")
def fixture_seeded(db: GraphDB):
    seed = _seed()
    data = "\n".join(f"{s.n3()} {p.n3()} {o.n3()} ." for s, p, o in seed)
    db.graph_clear(GRAPH)
    db.query(f"INSERT DATA {{ GRAPH <{GRAPH}> {{\n{data}\n}} }}", update=True)
    yield seed
    db.graph_clear(GRAPH)


def test_a_text_construct_returns_exactly_the_constructed_triples(db, seeded):
    result = db.query(
        f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}"
    )

    assert isinstance(result, Graph)
    assert isomorphic(result, seeded)


def test_a_text_construct_after_a_prologue_returns_a_graph(db, seeded):
    result = db.query(
        PROLOGUE
        + f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}"
    )

    assert isinstance(result, Graph)
    assert isomorphic(result, seeded)


def test_a_text_describe_returns_exactly_the_description(db, seeded):
    result = db.query(PROLOGUE + f"DESCRIBE ex:s FROM <{GRAPH}>")

    assert isinstance(result, Graph)
    assert isomorphic(result, _about_s(seeded))


def test_a_built_construct_returns_exactly_the_constructed_triples(db, seeded):
    built = SPARQLQuery.construct(["?s ?p ?o ."], ["?s ?p ?o ."], named_graph=GRAPH)

    result = db.query(built)

    assert isinstance(result, Graph)
    assert isomorphic(result, seeded)


def test_a_built_explicit_only_construct_returns_the_explicit_triples(db, seeded):
    """Explicit only, without a named graph: the default graph of every explicit statement,
    narrowed to the seed's namespace by a filter."""
    built = SPARQLQuery.construct(
        ["?s ?p ?o ."],
        ["?s ?p ?o .", f'FILTER(STRSTARTS(STR(?p), "{EX}"))'],
        include_implicit=False,
    )

    result = db.query(built)

    assert isinstance(result, Graph)
    assert isomorphic(result, seeded)


def test_a_built_describe_returns_exactly_the_description(db, seeded):
    built = SPARQLQuery.describe([S], named_graph=GRAPH)

    result = db.query(built)

    assert isinstance(result, Graph)
    assert isomorphic(result, _about_s(seeded))


def test_a_paged_text_construct_returns_that_page(db, seeded):
    page = db.query(
        f"PREFIX ex: <{EX}>\n"
        "CONSTRUCT { ?s ex:rank ?r } "
        f"WHERE {{ GRAPH <{GRAPH}> {{ ?s ex:rank ?r }} }} "
        "ORDER BY ?r LIMIT 2 OFFSET 2"
    )

    expected = Graph()
    for rank in (2, 3):
        expected.add(
            (
                URIRef(f"{EX}item{rank}"),
                URIRef(EX + "rank"),
                Literal(rank, datatype=XSD.integer),
            )
        )
    assert isinstance(page, Graph)
    assert isomorphic(page, expected)
    assert len(seeded) > len(page)


def test_a_select_and_an_ask_after_a_prologue_answer_as_before(db, seeded):
    rows = db.query(
        PROLOGUE + f"SELECT ?o WHERE {{ GRAPH <{GRAPH}> {{ ex:s ex:p ?o }} }}"
    )
    found = db.query(PROLOGUE + f"ASK {{ GRAPH <{GRAPH}> {{ ex:s ex:p ex:o }} }}")

    assert isinstance(rows, dict)
    assert [row["o"]["value"] for row in rows["results"]["bindings"]] == [EX + "o"]
    assert found["boolean"] is True
