"""The checked write: a write and its precondition in one update request.

The store answers every SPARQL update with success, whether the update changed anything or
not. So a write that must report whether its precondition held cannot learn it from the
response. A separate `ASK` before the write can be stale by the time the write runs.

A checked write puts the precondition into the `WHERE` of the update itself and adds one
receipt triple to its `INSERT`. The receipt lands only when the `WHERE` matched, in the same
commit as the change. One `ASK` for the receipt afterwards tells whether the write was
applied. A checked write thus sends two requests: the update and the `ASK`.

The lifetime of a receipt: when the `ASK` has found it, the client keeps it, behind a lock,
as a receipt to remove. The next checked write of the client, from any thread, takes every
receipt to remove and appends one `DELETE WHERE` operation per receipt to its own update
request, after its own update. The store runs all operations of one update request in one
transaction, so a commit costs the store one write transaction, not two. If that request fails
(a refusal, an error status, no answer), the receipts it carried stay to remove: the store
rolled the whole request back or applied it, and a second removal of a receipt that is gone
changes nothing. If its precondition is false, the removals that it carried were applied.
`GraphDB.close()` removes the receipts still to remove, in one request, before it closes the
sessions. A receipt that outlives its process (the process stopped before a later write or
`close()`) keeps its time, so that a later sweep can find it.

Scope: the precondition reads the **explicit** triples of the target graph only. With a named
graph, `WITH <g>` does that, because inferred triples are always in the default graph. Without
one, `USING <DEFAULT_GRAPH>` restricts the `WHERE` to the explicit triples of the default graph,
and the removals are written in `GRAPH <DEFAULT_GRAPH> { … }`, so that the delete acts on the
same graph that the check read. A bare removal template would also remove copies of the triple
in every named graph.

The contract: a normal return means that the store evaluated the precondition as true and
committed the change. The store isolates commits only ("read committed"): another writer can
commit between the evaluation of the `WHERE` and the commit of this write. An invariant that
must hold under concurrent writers belongs in a SHACL shape, which the store checks when it
commits.
"""

import threading
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, TYPE_CHECKING
from uuid import uuid4

from rdflib import BNode, Literal, URIRef, XSD

from kapps_triplestore_interface.exceptions import (
    InvalidInputError,
    PreconditionFailedError,
)
from kapps_triplestore_interface.utils import utils
from kapps_triplestore_interface.utils.iri import IRI
from kapps_triplestore_interface.utils.types import (
    GraphName,
    PartialTriple,
    Subject,
    SubjectLike,
    Triple,
)

if TYPE_CHECKING:
    from kapps_triplestore_interface import GraphDB

# The graph that holds receipts, and the predicate that carries a receipt's time. A receipt
# that outlives its process (the process stopped before its removal) keeps its time, so that a
# later sweep can find it.
RECEIPT_GRAPH = URIRef("urn:x-kapps:write-receipts")
RECEIPT_PREDICATE = URIRef("urn:x-kapps:appliedAt")

# The default graph alone, without the named graphs and without inferred triples, as a dataset
# for `USING` and as a graph for `GRAPH`. The store's own IRI for the graph without a name.
DEFAULT_GRAPH = URIRef("http://rdf4j.org/schema/rdf4j#nil")


class ReceiptsToRemove:
    """The receipts of one client whose `ASK` has found them, still to remove, behind a lock.

    `take` empties the list in one step, so that two writes never carry the same receipt.
    `put_back` returns the receipts of a request that failed, ahead of the newer ones.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._receipts: List[URIRef] = []

    def add(self, receipt: URIRef) -> None:
        with self._lock:
            self._receipts.append(receipt)

    def take(self) -> List[URIRef]:
        with self._lock:
            receipts, self._receipts = self._receipts, []
        return receipts

    def put_back(self, receipts: Sequence[URIRef]) -> None:
        if not receipts:
            return
        with self._lock:
            self._receipts[:0] = receipts

    def __len__(self) -> int:
        with self._lock:
            return len(self._receipts)

    def __iter__(self):
        with self._lock:
            return iter(list(self._receipts))


# Guards the creation of the list on a client that `__init__` did not build (a test double
# made with `GraphDB.__new__`). `GraphDB.__init__` creates the list itself.
_RECEIPTS_LOCK = threading.Lock()


def receipts_to_remove(db: "GraphDB") -> ReceiptsToRemove:
    """The client's receipts to remove, created on first use if the client has none."""
    receipts = getattr(db, "_receipts_to_remove", None)
    if receipts is None:
        with _RECEIPTS_LOCK:
            receipts = getattr(db, "_receipts_to_remove", None)
            if receipts is None:
                receipts = ReceiptsToRemove()
                db._receipts_to_remove = receipts
    return receipts


def receipt_pattern(receipt: URIRef) -> str:
    """`GRAPH <receipt graph> { <receipt> ?p ?o }`, for the `ASK` and for the removal."""
    return f"GRAPH {RECEIPT_GRAPH.n3()} {{ {receipt.n3()} ?p ?o }}"


def render_removals(receipts: Sequence[URIRef]) -> str:
    """One `DELETE WHERE` operation per receipt, joined with `;`.

    One operation per receipt, not one pattern per receipt in one `DELETE WHERE`: the patterns
    of one `WHERE` are joined, so one receipt that is gone already would keep all from removal.
    """
    return " ;\n".join(
        f"DELETE WHERE {{ {receipt_pattern(receipt)} }}" for receipt in receipts
    )


def remove_receipts(db: "GraphDB") -> None:
    """Remove every receipt still to remove, in one update request; send none if there is none.

    A failure keeps the receipts to remove and is logged as a warning, not raised: each receipt
    carries its time for a later sweep.
    """
    pending = receipts_to_remove(db)
    receipts = pending.take()
    if not receipts:
        return
    try:
        db.query(query=render_removals(receipts), update=True)
    except Exception as error:
        pending.put_back(receipts)
        db.logger.warning(
            f"The receipts {', '.join(r.n3() for r in receipts)} in {RECEIPT_GRAPH.n3()} "
            f"could not be removed ({error}). Each carries its time for a later sweep."
        )


def render_term(
    term,
    bn_map: Optional[Dict[BNode, str]] = None,
    prefix: str = "",
) -> str:
    """Render a term for a pattern. A blank node becomes a variable, one per node."""
    if isinstance(term, BNode):
        if bn_map is None:
            raise InvalidInputError(
                "Blank nodes in predicates are not supported for updates."
            )
        if term not in bn_map:
            bn_map[term] = f"?{prefix}{len(bn_map) + 1}"
        return bn_map[term]
    if hasattr(term, "n3"):
        return term.n3()
    return IRI(term).n3()


def build_patterns(
    triples: Iterable[Triple],
    bn_map: Dict[BNode, str],
    prefix: str,
) -> List[str]:
    """Render triples as `s p o .` patterns, with blank nodes as variables from `bn_map`."""
    patterns: List[str] = []
    for subject, predicate, obj in triples:
        subj_str = render_term(subject, bn_map, prefix)
        pred_str = render_term(predicate)
        obj_str = render_term(obj, bn_map, prefix)
        patterns.append(f"{subj_str} {pred_str} {obj_str} .")
    return patterns


def _format_block(patterns: List[str], indent: str = "  ") -> str:
    return "\n".join(f"{indent}{pattern}" for pattern in patterns)


def none_exist_filter(triples: Sequence[Triple]) -> str:
    """`FILTER NOT EXISTS { { group1 } UNION { group2 } … }`: none of the triples exists.

    Triples that share a blank node form one group and must match together, as in
    `any_triple_exists`. Each group's blank nodes are variables of their own.
    """
    groups = utils.group_triples_by_bnode(list(triples))
    union_parts = []
    for index, group in enumerate(groups, start=1):
        patterns = build_patterns(group, {}, f"x{index}_")
        union_parts.append("{\n" + _format_block(patterns, "      ") + "\n    }")
    return "FILTER NOT EXISTS {\n    " + "\n    UNION\n    ".join(union_parts) + "\n  }"


def absent_subject_filter(subject: Subject, index: int) -> str:
    """`FILTER NOT EXISTS { <s> ?p ?o }`: the subject has no triple in the scope."""
    return f"FILTER NOT EXISTS {{ {subject.n3()} ?a{index}p ?a{index}o . }}"


def sanitize_absent_subjects(
    absent_subjects: Optional[Iterable[SubjectLike]],
) -> List[IRI]:
    """Validate `absent_subjects` as IRIs. A blank node names nothing that the store holds."""
    if not absent_subjects:
        return []
    if isinstance(absent_subjects, (str, URIRef)):
        raise InvalidInputError(
            f"'absent_subjects' must be a list of IRIs, not a single value: {absent_subjects}"
        )
    subjects: List[IRI] = []
    for subject in absent_subjects:
        if isinstance(subject, BNode) or utils.BNODE_PATTERN.match(str(subject)):
            raise InvalidInputError(
                f"'absent_subjects' takes IRIs; a blank node cannot be checked: {subject}"
            )
        subjects.append(subject if isinstance(subject, IRI) else IRI(subject))
    return list(dict.fromkeys(subjects))


def render_update(
    old_triples: Sequence[Triple],
    new_triples: Sequence[Triple],
    named_graph: Optional[GraphName],
    filters: Sequence[str] = (),
    receipt: Optional[URIRef] = None,
    applied_at: Optional[str] = None,
) -> str:
    """Render `DELETE {old} INSERT {new} WHERE {old}`.

    Without `receipt`, the text is the unchecked update that `triples_update` has always sent.
    With it, the update also inserts the receipt, carries `filters` in its `WHERE`, and
    restricts its scope to the explicit triples of the target graph (see the module docstring).

    A blank node in both lists is the same node and renders as the same variable. A blank node
    only in `new_triples` is minted with `BIND(BNODE())`.
    """
    # One map across both sides: a BNode occurring in old_triples and in new_triples is
    # the *same* node, so it must render as the same SPARQL variable. A separate variable
    # on the new side would be bound by BIND(BNODE()) below, minting a replacement node
    # and orphaning every triple the caller had not listed in old_triples.
    bn_var_map: Dict[BNode, str] = {}

    old_patterns = build_patterns(old_triples, bn_var_map, "bn")
    bn_bound_by_where = set(bn_var_map)
    insert_patterns = build_patterns(new_triples, bn_var_map, "bn")

    # Only blank nodes exclusive to the new side need minting; the rest are already
    # bound by the WHERE clause.
    new_only_bn_vars = [
        var for bnode, var in bn_var_map.items() if bnode not in bn_bound_by_where
    ]

    where_patterns = list(dict.fromkeys(old_patterns))
    where_parts: List[str] = []
    if where_patterns:
        where_parts.append(_format_block(where_patterns))
    where_parts.extend(f"  {f}" for f in filters)
    where_parts.extend(f"  BIND(BNODE() AS {var})" for var in new_only_bn_vars)
    where_block = "\n".join(where_parts)

    if receipt is None:
        graph_clause = f"WITH {named_graph.n3()}\n" if named_graph else ""
        return f"""{graph_clause}DELETE {{
{_format_block(old_patterns)}
}}
INSERT {{
{_format_block(insert_patterns)}
}}
WHERE {{
{where_block}
}}
""".strip()

    receipt_block = (
        f"  GRAPH {RECEIPT_GRAPH.n3()} {{ {receipt.n3()} {RECEIPT_PREDICATE.n3()} "
        f"{applied_at} . }}"
    )
    parts: List[str] = []
    if named_graph:
        parts.append(f"WITH {named_graph.n3()}")
        if old_patterns:
            parts.append(f"DELETE {{\n{_format_block(old_patterns)}\n}}")
    elif old_patterns:
        parts.append(
            f"DELETE {{\n  GRAPH {DEFAULT_GRAPH.n3()} {{\n"
            f"{_format_block(old_patterns, '    ')}\n  }}\n}}"
        )
    insert_lines = [_format_block(insert_patterns)] if insert_patterns else []
    insert_lines.append(receipt_block)
    parts.append("INSERT {\n" + "\n".join(insert_lines) + "\n}")
    if not named_graph:
        parts.append(f"USING {DEFAULT_GRAPH.n3()}")
    parts.append(f"WHERE {{\n{where_block}\n}}")
    return "\n".join(parts)


def checked_write(
    db: "GraphDB",
    operation: str,
    old_triples: Sequence[Triple],
    new_triples: Sequence[Triple],
    named_graph: Optional[GraphName],
    precondition: str,
    named_triples: Sequence[PartialTriple],
    filters: Sequence[str] = (),
) -> bool:
    """Send one update with its precondition and a receipt, then read the receipt.

    The update request also carries the removal of every receipt that the client still has to
    remove, as further operations after the update (see the module docstring). The receipt of
    this write joins them once its `ASK` has found it.

    Args:
        db (GraphDB): The client.
        operation (str): The public function's name, for messages.
        old_triples (Sequence[Triple]): Triples that must exist, and are removed.
        new_triples (Sequence[Triple]): Triples to insert.
        named_graph (Optional[GraphName]): The target graph, or `None` for the default graph.
        precondition (str): The precondition in words, for the error message.
        named_triples (Sequence[PartialTriple]): What the error names as `.triples`.
        filters (Sequence[str]): Further `FILTER` clauses of the precondition.

    Returns:
        bool: True. A false precondition raises instead of returning False.

    Raises:
        PreconditionFailedError: The store found the precondition false; nothing of the write
            was written. The removals that the request carried were applied.
        TripleStoreResponseError: The store refused a request. A failure of the write itself
            propagates unchanged, and the receipt is not consulted: the store may still commit it.
            The receipts that the request carried stay to remove.
        TripleStoreUnavailableError: A request got no answer, for example a timeout. For the
            write, as above: it propagates unchanged, the write is not sent again, the receipt
            is not consulted, and the receipts that the request carried stay to remove.
    """
    receipt = URIRef(f"urn:uuid:{uuid4()}")
    applied_at = Literal(datetime.now(timezone.utc), datatype=XSD.dateTime).n3()
    update = render_update(
        old_triples,
        new_triples,
        named_graph,
        filters=filters,
        receipt=receipt,
        applied_at=applied_at,
    )
    # The write's own update stays the first operation of the request; the removals follow.
    pending = receipts_to_remove(db)
    carried = pending.take()
    request = f"{update} ;\n{render_removals(carried)}" if carried else update
    try:
        db.query(query=request, update=True)
    except BaseException:
        pending.put_back(carried)
        raise

    answer = db.query(query=f"ASK {{ {receipt_pattern(receipt)} }}", update=False)
    graph_name = named_graph.n3() if named_graph else "the default graph"

    if not (answer and answer.get("boolean") is True):
        message = (
            f"{operation}: the store found the precondition false in {graph_name} "
            f"({precondition}), so nothing was written."
        )
        db.logger.debug(f"{message} repository: {db._repository}")
        raise PreconditionFailedError(
            message,
            triples=list(named_triples),
            named_graph=named_graph,
        )

    # Only now: a receipt that another write removed before this `ASK` would read as a false
    # precondition.
    pending.add(receipt)
    db.logger.debug(
        f"{operation}: applied in {graph_name}, repository: {db._repository}"
    )
    return True
