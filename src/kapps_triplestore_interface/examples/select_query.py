"""Example 1: connect, write two facts, and read them back with one SELECT.

Start the GraphDB first (see README.md in this directory), then run:

    python select_query.py

What it shows: how ``connect()`` opens a store, how ``query`` returns the store's answer,
and how to turn that answer into Python values. It also shows the one rule about IRIs that
fails silently when it is missed: ``IRI.short`` returns a prettified form such as
``rdfs:label``. That form is for reading only. When your next query needs an IRI, take it from
the result, not from the printed text.
"""

from _store import NAMESPACE, graph_name, open_store  # pylint: disable=import-error
from rdflib import RDF, RDFS, Literal, URIRef

from kapps_triplestore_interface import IRI, process_bindings_select

EXAMPLE = "select_query"


def main() -> None:
    store = open_store()
    graph = graph_name(EXAMPLE)
    store.graph_clear(graph)
    print(f"Connected to repository '{store.dataset}'; working in graph <{graph}>.")

    belt = IRI(NAMESPACE + "Belt1")
    store.triples_add(
        [
            (belt, RDF.type, URIRef(NAMESPACE + "ConveyorBelt")),
            (belt, RDFS.label, Literal("Belt 1")),
        ],
        named_graph=graph,
    )
    print("Wrote 2 triples with triples_add.")

    answer = store.query(f"""
        SELECT ?thing ?predicate ?object
        WHERE {{
            GRAPH <{graph}> {{ ?thing ?predicate ?object }}
        }}
        ORDER BY ?predicate
        """)
    rows = process_bindings_select(
        answer["results"]["bindings"], variables=["thing", "predicate", "object"]
    )

    print("\nThe answer, with the IRIs prettified for a person (IRI.short):")
    for thing, predicate, obj in rows:
        print(f"  {thing.short}  {predicate.short}  {obj}")

    # The prettified text is display-only. The value in `rows` is the IRI itself, and that is
    # what goes into the next query.
    thing = rows[0][0]
    print(
        f"\nThe IRI to use in the next query is the value in the result: {str(thing)}"
    )
    print("Its triples:")
    for triple in store.triples_get(
        sub=thing, include_implicit=False, named_graph=graph
    ):
        print("  ", triple)


if __name__ == "__main__":
    main()
