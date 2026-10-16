"""Live test: a leftover write receipt does not break converted reads, `graphs_get` or the clear.

A dead process leaves its receipt in the receipt graph. The test writes one on purpose, with a
raw SPARQL update, then reads it back and clears the graph.
"""

from uuid import uuid4

from kapps_triplestore_interface import GraphDB, IRI
from kapps_triplestore_interface.queries.checked_write import (
    RECEIPT_GRAPH,
    RECEIPT_PREDICATE,
)


def test_a_leftover_receipt_is_read_listed_and_cleared(db: GraphDB):
    receipt = f"urn:uuid:{uuid4()}"
    db.graph_clear(RECEIPT_GRAPH)
    try:
        db.query(
            f"INSERT DATA {{ GRAPH {RECEIPT_GRAPH.n3()} "
            f'{{ <{receipt}> {RECEIPT_PREDICATE.n3()} "2026-10-11T10:00:00Z" }} }}',
            update=True,
        )

        rows = db.query(
            "SELECT ?g ?s ?p WHERE { GRAPH ?g { ?s ?p ?o } }",
            convert_bindings=True,
        )["results"]["bindings"]
        found = [row for row in rows if row["s"] == receipt]
        assert len(found) == 1
        assert isinstance(found[0]["s"], IRI)
        assert isinstance(found[0]["g"], IRI)
        assert found[0]["g"] == str(RECEIPT_GRAPH)

        assert str(RECEIPT_GRAPH) in [str(graph) for graph in db.graphs_get()]
    finally:
        assert db.graph_clear(RECEIPT_GRAPH) is True
