"""A literal whose datatype `XSDToPythonMapper` has no converter for, against a live store.

It reads back as an `rdflib.Literal` that keeps the datatype. Writing that value again stores
the same typed literal, so a read-modify-write cycle does not re-type it.
"""

from kapps_triplestore_interface import GraphDB
from rdflib import Literal
import pytest

NAMED_GRAPH = "http://example.org/unknown_datatypes_graph"
SUB = "http://example.org#measurement1"
PRED = "http://example.org#hasValue"
PRED_COPY = "http://example.org#hasCopiedValue"

VALUES = [
    Literal(
        '{"n_components":1,"dimensions":1,"weights":[1.0],"means":[[25.0]]}',
        datatype="http://example.org/ontology/uncertainty#gmmLiteral",
    ),
    Literal(
        "POINT(8.41 49.01)",
        datatype="http://www.opengis.net/ont/geosparql#wktLiteral",
    ),
]


@pytest.fixture(params=VALUES, ids=["gmmLiteral", "wktLiteral"])
def stored(request, db: GraphDB):
    value = request.param
    db.triples_add([(SUB, PRED, value)], named_graph=NAMED_GRAPH)
    yield value
    db.triples_delete(
        [(SUB, PRED, value), (SUB, PRED_COPY, value)],
        named_graph=NAMED_GRAPH,
        check_exist=False,
    )


def test_reads_back_as_a_literal_and_writes_back_unchanged(
    db: GraphDB, stored: Literal
):
    [(_, _, value)] = db.triples_get(sub=SUB, pred=PRED, named_graph=NAMED_GRAPH)
    assert isinstance(value, Literal)
    assert value == stored

    db.triples_add([(SUB, PRED_COPY, value)], named_graph=NAMED_GRAPH)
    [(_, _, copy)] = db.triples_get(sub=SUB, pred=PRED_COPY, named_graph=NAMED_GRAPH)
    assert copy == stored
