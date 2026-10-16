"""Live tests of the checked write: what the store does with the update, its precondition
and its receipt.

Every test starts from an empty default graph, an empty test graph and an empty receipt
graph, with one schema triple, `x:p1 rdfs:subPropertyOf x:q`, so that `s x:p1 o` makes
`s x:q o` inferred. The store's explicit statements are read from the statements endpoint
with `infer=false`, so that a check of "nothing was written" covers every graph.
"""

import json
import os
import threading
from typing import Optional

import pytest
from rdflib import BNode, Literal, URIRef

from kapps_triplestore_interface import GraphDB, IRI, PreconditionFailedError
from kapps_triplestore_interface.queries.checked_write import RECEIPT_GRAPH
from kapps_triplestore_interface.utils import utils

X = "http://example.org/checked#"
GRAPH = "http://example.org/checked_write_graph"

P1 = IRI(X + "p1")
Q = IRI(X + "q")
R = IRI(X + "r")
A = IRI(X + "a")
B = IRI(X + "b")
O = IRI(X + "o")
NEW = IRI(X + "new")

SCHEMA = (P1, IRI("rdfs:subPropertyOf"), Q)

# Set to a file path to keep the concurrency test's counts, for example in a CI artifact.
CONCURRENCY_REPORT_ENV = "CHECKED_WRITE_CONCURRENCY_REPORT"


def _explicit(db: GraphDB, graph: Optional[str] = "any") -> set:
    """The explicit statements as N-Quads lines: of every graph, of one, or (None) of the default."""
    params = {"infer": "false"}
    if graph is None:
        params["context"] = "null"
    elif graph != "any":
        params["context"] = URIRef(graph).n3()
    response = db._make_request(
        "get",
        f"repositories/{db.dataset}/statements",
        params=params,
        headers={"Accept": "application/n-quads"},
    )
    assert response.status_code == 200, response.text
    return {line for line in response.text.splitlines() if line.strip()}


def _has(db: GraphDB, triple, graph: Optional[str]) -> bool:
    """Whether the triple is explicit in exactly this graph (None: the default graph)."""
    s, p, o = utils.sanitize_triple(triple)
    line = f"{s.n3()} {p.n3()} {o.n3()}"
    return any(q.startswith(line + " ") for q in _explicit(db, graph))


def _visible(db: GraphDB, triple) -> bool:
    """Whether a read sees the triple: every graph, explicit or inferred."""
    return bool(db.query(f"ASK {{ {utils.triple_to_string(triple)} }}")["boolean"])


def _receipts(db: GraphDB) -> int:
    return len(_explicit(db, str(RECEIPT_GRAPH)))


def _seed(db: GraphDB, triples, graph: Optional[str]) -> None:
    assert db.triples_add(triples, check_exist=False, named_graph=graph) is True


@pytest.fixture
def store(db: GraphDB):
    """An empty store with the schema triple. Restores the client's default graph after."""
    saved = db.named_graph
    db.named_graph = None

    def wipe():
        db.graph_clear(None)
        db.graph_clear(GRAPH)
        db.query(f"DROP SILENT GRAPH {RECEIPT_GRAPH.n3()}", update=True)

    wipe()
    _seed(db, [SCHEMA], None)
    yield db
    wipe()
    db.named_graph = saved


@pytest.fixture(params=[None, GRAPH], ids=["default-graph", "named-graph"])
def graph(request) -> Optional[str]:
    return request.param


def _expected_graph(graph):
    return IRI(graph) if graph else None


# --- a true precondition applies and leaves no receipt --------------------------------


def test_add_applies(store, graph):
    assert store.triples_add(
        [(A, R, Literal(1)), (A, R, Literal(2))], named_graph=graph
    )
    assert _has(store, (A, R, Literal(1)), graph)
    assert _has(store, (A, R, Literal(2)), graph)
    assert _receipts(store) == 0


def test_delete_applies(store, graph):
    _seed(store, [(A, R, Literal(1)), (A, R, Literal(2))], graph)
    assert store.triples_delete(
        [(A, R, Literal(1)), (A, R, Literal(2))], named_graph=graph
    )
    assert not _has(store, (A, R, Literal(1)), graph)
    assert not _has(store, (A, R, Literal(2)), graph)
    assert _receipts(store) == 0


def test_update_applies(store, graph):
    _seed(store, [(A, R, Literal(1))], graph)
    assert store.triples_update(
        [(A, R, Literal(1))],
        [(A, R, Literal(2)), (B, R, Literal(3))],
        named_graph=graph,
    )
    assert not _has(store, (A, R, Literal(1)), graph)
    assert _has(store, (A, R, Literal(2)), graph)
    assert _has(store, (B, R, Literal(3)), graph)
    assert _receipts(store) == 0


def test_single_delete_applies(store, graph):
    _seed(store, [(A, R, O)], graph)
    assert store.triple_delete((A, R, O), named_graph=graph) is True
    assert not _has(store, (A, R, O), graph)
    assert _receipts(store) == 0


def test_single_update_applies(store, graph):
    _seed(store, [(A, R, O)], graph)
    assert store.triple_update((A, R, O), new_obj=NEW, named_graph=graph) is True
    assert not _has(store, (A, R, O), graph)
    assert _has(store, (A, R, NEW), graph)
    assert _receipts(store) == 0


# --- a false precondition raises, writes nothing and leaves no receipt -----------------


def _refused(store, graph, call, named):
    before = _explicit(store)
    with pytest.raises(PreconditionFailedError) as refused:
        call()
    assert _explicit(store) == before
    assert _receipts(store) == 0
    assert refused.value.triples == [utils.sanitize_triple(t) for t in named]
    assert refused.value.named_graph == _expected_graph(graph)


def test_add_refused(store, graph):
    _seed(store, [(A, R, Literal(1))], graph)
    triples = [(A, R, Literal(1)), (A, R, Literal(2))]
    _refused(
        store, graph, lambda: store.triples_add(triples, named_graph=graph), triples
    )
    assert not _has(store, (A, R, Literal(2)), graph)


def test_delete_refused(store, graph):
    _seed(store, [(A, R, Literal(1))], graph)
    triples = [(A, R, Literal(1)), (A, R, Literal(2))]
    _refused(
        store, graph, lambda: store.triples_delete(triples, named_graph=graph), triples
    )
    assert _has(store, (A, R, Literal(1)), graph)


def test_update_refused(store, graph):
    _seed(store, [(A, R, Literal(1))], graph)
    old = [(A, R, Literal(1)), (A, R, Literal(9))]
    _refused(
        store,
        graph,
        lambda: store.triples_update(old, [(A, R, Literal(2))], named_graph=graph),
        old,
    )


def test_single_delete_refused(store, graph):
    _refused(
        store,
        graph,
        lambda: store.triple_delete((A, R, O), named_graph=graph),
        [(A, R, O)],
    )


def test_single_update_refused(store, graph):
    _refused(
        store,
        graph,
        lambda: store.triple_update((A, R, O), new_obj=NEW, named_graph=graph),
        [(A, R, O)],
    )


def test_a_triple_in_another_graph_does_not_satisfy_the_precondition(store, graph):
    """The scope is the target graph: a copy elsewhere is not the triple to delete."""
    other = None if graph else GRAPH
    _seed(store, [(A, R, O)], other)
    _refused(
        store,
        graph,
        lambda: store.triple_delete((A, R, O), named_graph=graph),
        [(A, R, O)],
    )
    assert _has(store, (A, R, O), other)


# --- inferred triples ------------------------------------------------------------------


def test_an_inferred_only_removal_raises(store, graph):
    """`a q o` is inferred from `a p1 o`. A delete cannot remove it, so the check refuses."""
    _seed(store, [(A, P1, O)], graph)
    assert _visible(store, (A, Q, O))

    _refused(
        store,
        graph,
        lambda: store.triple_delete((A, Q, O), named_graph=graph),
        [(A, Q, O)],
    )
    _refused(
        store,
        graph,
        lambda: store.triples_update([(A, Q, O)], [(A, Q, NEW)], named_graph=graph),
        [(A, Q, O)],
    )
    assert _visible(store, (A, Q, O))


def test_explicit_and_inferred_stays_visible_after_a_delete(store, graph):
    """The EI limit: a delete clears only the explicit flag, and the inference remains."""
    _seed(store, [(A, P1, O)], None)
    _seed(store, [(A, Q, O)], graph)

    assert store.triple_delete((A, Q, O), named_graph=graph) is True

    assert not _has(store, (A, Q, O), graph)
    assert _visible(store, (A, Q, O))
    assert _receipts(store) == 0


# --- absent_subjects -------------------------------------------------------------------


@pytest.mark.parametrize("write", ["triples_add", "triples_update"])
def test_an_existing_subject_raises(store, graph, write):
    _seed(store, [(A, R, O)], graph)
    new = [(A, R, NEW)]
    call = {
        "triples_add": lambda: store.triples_add(
            new, named_graph=graph, absent_subjects=[A]
        ),
        "triples_update": lambda: store.triples_update(
            [], new, named_graph=graph, absent_subjects=[A]
        ),
    }[write]
    named = (new if write == "triples_add" else []) + [(A, None, None)]
    before = _explicit(store)
    with pytest.raises(PreconditionFailedError) as refused:
        call()
    assert _explicit(store) == before
    assert _receipts(store) == 0
    assert refused.value.triples == [
        t if None in t else utils.sanitize_triple(t) for t in named
    ]


@pytest.mark.parametrize("write", ["triples_add", "triples_update"])
def test_a_forward_reference_does_not_raise(store, graph, write):
    """A subject that occurs only as an object (`b r a`) has no triple of its own yet."""
    _seed(store, [(B, R, A)], graph)
    new = [(A, R, NEW)]
    if write == "triples_add":
        assert store.triples_add(new, named_graph=graph, absent_subjects=[A]) is True
    else:
        assert store.triples_update([], new, named_graph=graph, absent_subjects=[A])
    assert _has(store, (A, R, NEW), graph)
    assert _receipts(store) == 0


def test_a_subject_in_another_graph_does_not_raise(store):
    """The known limit: the scope is the target graph, so a subject elsewhere passes."""
    _seed(store, [(A, R, O)], None)
    assert store.triples_add([(A, R, NEW)], named_graph=GRAPH, absent_subjects=[A])
    assert _has(store, (A, R, NEW), GRAPH)


def test_update_with_old_triples_and_absent_subjects(store, graph):
    """Either failing half of the precondition refuses the whole write."""
    _seed(store, [(A, R, Literal(1)), (B, R, O)], graph)
    old, new = [(A, R, Literal(1))], [(A, R, Literal(2)), (NEW, R, O)]

    # the old triple exists, the subject B exists: refused
    before = _explicit(store)
    with pytest.raises(PreconditionFailedError):
        store.triples_update(old, new, named_graph=graph, absent_subjects=[B])
    # the old triple is missing, the subject NEW is absent: refused
    with pytest.raises(PreconditionFailedError):
        store.triples_update(
            [(A, R, Literal(7))], new, named_graph=graph, absent_subjects=[NEW]
        )
    assert _explicit(store) == before
    assert _receipts(store) == 0

    # both hold: applied
    assert store.triples_update(old, new, named_graph=graph, absent_subjects=[NEW])
    assert _has(store, (NEW, R, O), graph)
    assert not _has(store, (A, R, Literal(1)), graph)


# --- blank nodes -----------------------------------------------------------------------


def test_a_blank_node_structure_is_checked_as_one(store, graph):
    """The add precondition matches a structure that shares a blank node, not its parts."""
    node = BNode()
    assert store.triples_add([(A, R, node), (node, Q, Literal(1))], named_graph=graph)

    # the same structure again, with a fresh blank node: it exists, so the add is refused
    again = BNode()
    with pytest.raises(PreconditionFailedError):
        store.triples_add([(A, R, again), (again, Q, Literal(1))], named_graph=graph)

    # a structure of which only one part matches (`a r _:x`) does not exist yet: applied
    other = BNode()
    assert store.triples_add([(A, R, other), (other, Q, Literal(2))], named_graph=graph)
    assert _receipts(store) == 0


def test_an_owl_intersection_adds_with_the_check(store, graph):
    """The shape in which two blank-node groups are joined by a later triple."""
    cls, restriction, cell = IRI(X + "C"), BNode(), BNode()
    triples = [
        (cls, IRI("owl:intersectionOf"), cell),
        (restriction, IRI("rdf:type"), IRI("owl:Restriction")),
        (cell, IRI("rdf:first"), restriction),
        (cell, IRI("rdf:rest"), IRI("rdf:nil")),
    ]
    assert store.triples_add(triples, named_graph=graph) is True
    with pytest.raises(PreconditionFailedError):
        store.triples_add(triples, named_graph=graph)


# --- the default graph -----------------------------------------------------------------


def test_a_checked_delete_without_a_graph_keeps_the_named_copy(store):
    """The check reads the default graph, so the delete acts on the default graph only."""
    _seed(store, [(A, R, O)], None)
    _seed(store, [(A, R, O)], GRAPH)

    assert store.triple_delete((A, R, O)) is True

    assert not _has(store, (A, R, O), None)
    assert _has(store, (A, R, O), GRAPH)


def test_an_unchecked_delete_without_a_graph_removes_every_copy(store):
    _seed(store, [(A, R, O)], None)
    _seed(store, [(A, R, O)], GRAPH)

    assert store.triple_delete((A, R, O), check_exist=False) is True

    assert not _has(store, (A, R, O), None)
    assert not _has(store, (A, R, O), GRAPH)


def test_an_unchecked_update_applies_only_on_a_match(store, graph):
    assert store.triples_update(
        [(A, R, O)], [(A, R, NEW)], check_exist=False, named_graph=graph
    )
    assert not _has(store, (A, R, NEW), graph)
    assert _receipts(store) == 0


# --- concurrency -----------------------------------------------------------------------

ROUNDS = 50


def test_two_writers_on_the_same_old_triple(store, graph):
    """Two threads replace the same old triple at once, 50 times.

    Expected per round: exactly one applies, and the other raises. A round in which both
    apply is the read-committed residual: the second `WHERE` read the old triple before the
    first commit removed it. Its rate is recorded, not hidden. A round in which both raise,
    or one returns without its change in the store, would be a defect.
    """
    counts = {"one_applied": 0, "both_applied": 0, "both_raised": 0}
    rounds = []
    old = (A, R, O)

    for round_ in range(ROUNDS):
        store.graph_clear(graph)
        store.graph_clear(None)
        _seed(store, [SCHEMA], None)
        _seed(store, [old], graph)
        barrier = threading.Barrier(2)
        outcome = {}

        def writer(name):
            new = (A, R, IRI(X + name))
            barrier.wait()
            try:
                outcome[name] = store.triples_update([old], [new], named_graph=graph)
            except PreconditionFailedError:
                outcome[name] = "raised"
            except Exception as error:  # reported below, never swallowed
                outcome[name] = error

        threads = [threading.Thread(target=writer, args=(n,)) for n in ("w1", "w2")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        unexpected = [v for v in outcome.values() if v not in (True, "raised")]
        assert not unexpected, f"round {round_}: {unexpected}"
        applied = sorted(n for n, v in outcome.items() if v is True)
        for name in ("w1", "w2"):
            # A normal return means that the change is in the store.
            if name in applied:
                assert _has(store, (A, R, IRI(X + name)), graph)
        assert not _has(store, old, graph) or not applied
        key = {1: "one_applied", 2: "both_applied", 0: "both_raised"}[len(applied)]
        counts[key] += 1
        rounds.append(applied)

    assert _receipts(store) == 0
    report = {"graph": graph or "default", "rounds": ROUNDS, **counts}
    print(f"\nconcurrency: {json.dumps(report)}")
    path = os.getenv(CONCURRENCY_REPORT_ENV)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(report) + "\n")

    assert counts["both_raised"] == 0
    assert counts["one_applied"] + counts["both_applied"] == ROUNDS
