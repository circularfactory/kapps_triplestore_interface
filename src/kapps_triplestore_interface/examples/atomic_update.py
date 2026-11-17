"""Example 2: replace a property in one atomic update, and why that is not two operations.

Start the GraphDB first (see README.md in this directory), then run:

    python atomic_update.py

A part is possessed by exactly one resource. Handing it over means replacing the value of
``possessedBy``. There are two ways to write that:

- ``triples_delete`` and then ``triples_add``. Between the two calls the store holds a part that
  nobody possesses. A reader in that moment sees it, and a SHACL shape such as "possessed by
  exactly one resource" would refuse the first step.
- ``triples_update`` with the old triple and the new triple. The removal and the insertion are one
  ``DELETE ... INSERT ... WHERE`` request, so no reader sees a state in between.

The update also checks its precondition. If the old triple is not there, nothing is written and
``PreconditionFailedError`` tells you so.
"""

from _store import NAMESPACE, graph_name, open_store  # pylint: disable=import-error

from kapps_triplestore_interface import IRI, PreconditionFailedError

EXAMPLE = "atomic_update"


def main() -> None:
    store = open_store()
    graph = graph_name(EXAMPLE)
    store.graph_clear(graph)

    part = IRI(NAMESPACE + "Part1")
    owner = IRI(NAMESPACE + "possessedBy")
    robot_a, robot_b, robot_c = (
        IRI(NAMESPACE + name) for name in ("RobotA", "RobotB", "RobotC")
    )

    def owners() -> list[str]:
        found = store.triples_get(
            sub=part, pred=owner, include_implicit=False, named_graph=graph
        )
        return [str(obj).rsplit("#", 1)[-1] for _, _, obj in found]

    store.triples_add([(part, owner, robot_a)], named_graph=graph)
    print(f"Start:                       owners = {owners()}")

    print("\nThe two-operation way:")
    store.triples_delete([(part, owner, robot_a)], named_graph=graph)
    print(
        f"  after triples_delete:      owners = {owners()}   <- a reader sees this state"
    )
    store.triples_add([(part, owner, robot_b)], named_graph=graph)
    print(f"  after triples_add:         owners = {owners()}")

    print("\nThe atomic way:")
    store.triples_update(
        old_triples=[(part, owner, robot_b)],
        new_triples=[(part, owner, robot_a)],
        named_graph=graph,
    )
    print(
        f"  after triples_update:      owners = {owners()}   <- there was no state in between"
    )

    print("\nA stale update, which names an old value that is not there:")
    try:
        store.triples_update(
            old_triples=[(part, owner, robot_c)],
            new_triples=[(part, owner, robot_b)],
            named_graph=graph,
        )
    except PreconditionFailedError as refused:
        print(f"  refused:                   {type(refused).__name__}")
    print(f"  after the refused update:  owners = {owners()}   <- nothing was written")


if __name__ == "__main__":
    main()
