"""Example 3: blank-node identity, and the update that keeps it.

Start the GraphDB first (see README.md in this directory), then run:

    python blank_node_identity.py

A blank node has no IRI. The ``BNode`` that you pass to a function is only a name that ties the
triples of one call together. It is not the node in the store, and the store chooses its own
label for that node. So a second call cannot refer to the node by the ``BNode`` of the first
call. It must describe the node by its triples.

``triples_update`` has one rule for this: a ``BNode`` that you pass on both sides of the call
means "the same node, with a new value". The node keeps its identity, and every triple on it
that you did not list stays attached. If you delete the structure and add it again, you get a
new node, and the triples that you did not list stay behind on the old node, which nothing
points at any more.
"""

from _store import NAMESPACE, graph_name, open_store  # pylint: disable=import-error
from rdflib import BNode, Literal

from kapps_triplestore_interface import IRI

EXAMPLE = "blank_node_identity"


def main() -> None:
    store = open_store()
    graph = graph_name(EXAMPLE)
    store.graph_clear(graph)

    belt = IRI(NAMESPACE + "Belt1")
    has_sensor = IRI(NAMESPACE + "hasSensor")
    has_value = IRI(NAMESPACE + "hasValue")
    has_unit = IRI(NAMESPACE + "hasUnit")

    def select(pattern: str) -> list[dict]:
        answer = store.query(f"SELECT * WHERE {{ GRAPH <{graph}> {{ {pattern} }} }}")
        return answer["results"]["bindings"]

    def sensor_id() -> str:
        (row,) = select(f"<{belt}> <{has_sensor}> ?sensor")
        return row["sensor"]["value"]

    def describe(label: str) -> None:
        values = [row["value"]["value"] for row in select(f"?s <{has_value}> ?value")]
        units = [
            row["unit"]["value"]
            for row in select(f"<{belt}> <{has_sensor}> ?s . ?s <{has_unit}> ?unit")
        ]
        stranded = [
            row["unit"]["value"]
            for row in select(
                f"?s <{has_unit}> ?unit . FILTER NOT EXISTS {{ <{belt}> <{has_sensor}> ?s }}"
            )
        ]
        print(f"  {label}")
        print(f"    sensor node in the store: {sensor_id()}")
        print(
            f"    value: {values}   unit on the belt's sensor: {units}   unit left behind: {stranded}"
        )

    sensor = BNode()
    store.triples_add(
        [
            (belt, has_sensor, sensor),
            (sensor, has_value, Literal(12.1)),
            (sensor, has_unit, Literal("m/s")),
        ],
        named_graph=graph,
    )
    print("A belt with a sensor node. The node has a value and a unit.")
    describe("start")
    first_id = sensor_id()

    print("\nThe update with the same BNode on both sides:")
    store.triples_update(
        old_triples=[(belt, has_sensor, sensor), (sensor, has_value, Literal(12.1))],
        new_triples=[(belt, has_sensor, sensor), (sensor, has_value, Literal(1.4))],
        named_graph=graph,
    )
    describe("after triples_update")
    print(
        f"    same node as before: {sensor_id() == first_id}   (the unit was not listed, and is still there)"
    )

    print("\nThe delete and add with a fresh BNode:")
    store.triples_delete(
        [(belt, has_sensor, sensor), (sensor, has_value, Literal(1.4))],
        named_graph=graph,
    )
    replacement = BNode()
    store.triples_add(
        [(belt, has_sensor, replacement), (replacement, has_value, Literal(12.1))],
        named_graph=graph,
    )
    describe("after triples_delete and triples_add")
    print(
        f"    same node as before: {sensor_id() == first_id}   (the unit stayed on the old node)"
    )


if __name__ == "__main__":
    main()
