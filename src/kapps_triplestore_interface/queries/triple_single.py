# To be imported into ..graph_db.py GraphDB class

from typing import Optional, TYPE_CHECKING
from kapps_triplestore_interface.queries import checked_write
from kapps_triplestore_interface.utils import utils
from kapps_triplestore_interface.utils.iri import IRI
from kapps_triplestore_interface.utils.types import (
    PartialTripleLike,
    SubjectLike,
    PredicateLike,
    ObjectLike,
    GraphNameLike,
    TripleLike,
)
from kapps_triplestore_interface.exceptions import InvalidInputError

from kapps_triplestore_interface.sparql_query import SPARQLQuery

if TYPE_CHECKING:
    from kapps_triplestore_interface import GraphDB


def triple_exists(
    self: "GraphDB",
    triple: TripleLike,
    named_graph: Optional[GraphNameLike] = None,
) -> bool:
    """
    Check whether a specific triple exists in the graph database.

    Args:
        triple (TripleLike): The triple `(subject, predicate, object)` to check.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.

    Returns:
        bool: True if the triple exists, False otherwise.
    """
    triple = utils.sanitize_triple(triple)
    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph

    query = SPARQLQuery.ask(
        where_clauses=[
            utils.triple_to_string(triple, "."),
        ],
        named_graph=named_graph,
    )
    result = self.query(query=query)
    if result is None or result["boolean"] is False:
        self.logger.debug(
            f"Unable to find triple ({utils.triple_to_string(triple)}), named_graph: {named_graph or "default"}, repository: {self._repository}"
        )
        return False

    self.logger.debug(
        f"Found triple ({utils.triple_to_string(triple)}), named_graph: {named_graph or "default"}, repository: {self._repository}"
    )
    return True


def triple_add(
    self: "GraphDB",
    triple: TripleLike,
    named_graph: Optional[GraphNameLike] = None,
) -> bool:
    """
    Add a triple to the graph database.

    Args:
        triple (TripleLike): The triple `(subject, predicate, object)` to insert.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.

    Returns:
        bool: True if the triple was inserted, False otherwise.
    """
    triple = utils.sanitize_triple(triple)
    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph

    query = SPARQLQuery.insert_data(
        triples=[triple],
        named_graph=named_graph,
    )
    result = self.query(query=query, update=True)
    if not result:
        self.logger.warning(
            f"Failed to insert triple: ({utils.triple_to_string(triple)}) named_graph: {named_graph or "default"}, repository: {self._repository}"
        )
        return False

    self.logger.debug(
        f"Successfully inserted triple: ({utils.triple_to_string(triple)}) named_graph: {named_graph or "default"}, repository: {self._repository}"
    )

    return True


def triple_delete(
    self: "GraphDB",
    triple: TripleLike,
    check_exist: Optional[bool] = True,
    named_graph: Optional[GraphNameLike] = None,
) -> bool:
    """
    Delete a single triple.

    A SPARQL DELETE operation succeeds even if the triple does not exist. With
    `check_exist=True`, the write is checked: the precondition that the triple exists and
    the delete are one update request, and a receipt written by the same update proves that
    it was applied. A normal return means that the store evaluated the precondition as true
    and committed the change. The store isolates commits only (read committed): another
    writer can commit between the evaluation of the precondition and the commit of this
    write. An invariant that must hold under concurrent writers belongs in a SHACL shape,
    which the store checks at the commit.

    The precondition and the delete see the explicit triples of the target graph only:
    `named_graph`, or the default graph without the named graphs. A triple that is only
    inferred fails the precondition. A triple that is both explicit and inferred stays
    visible after a delete, because a delete clears only the explicit flag.

    Args:
        triple (TripleLike): The triple `(subject, predicate, object)` to delete.
        check_exist (Optional[bool]): If True, the precondition is that the triple exists.
            Defaults to True. If False, the triple is deleted unchecked: a missing triple is a
            no-op, and without a named graph the delete acts on every graph.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.

    Returns:
        bool: True. A false precondition raises instead of returning False.

    Raises:
        PreconditionFailedError: The triple was not an explicit triple of the target graph,
            and nothing was deleted. Its `.triples` is `[triple]`.
    """
    triple = utils.sanitize_triple(triple)
    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph

    if check_exist:
        return checked_write.checked_write(
            self,
            operation="triple_delete",
            old_triples=[triple],
            new_triples=[],
            named_graph=named_graph,
            precondition="the triple exists",
            named_triples=[triple],
        )

    query = SPARQLQuery.delete_data(
        triples=[triple],
        named_graph=named_graph,
    )
    self.query(query=query, update=True)

    self.logger.debug(
        f"Successfully deleted triple: ({utils.triple_to_string(triple)}), named_graph: {named_graph or "default"}, repository: {self._repository}"
    )
    return True


def triple_update(
    self: "GraphDB",
    old_triple: TripleLike,
    new_triple: Optional[PartialTripleLike] = None,
    new_sub: Optional[SubjectLike] = None,
    new_pred: Optional[PredicateLike] = None,
    new_obj: Optional[ObjectLike] = None,
    check_exist: Optional[bool] = True,
    named_graph: Optional[GraphNameLike] = None,
) -> bool:
    """
    Update a triple by replacing any of its parts.

    Performs a SPARQL `DELETE ... INSERT ... WHERE` that replaces the old triple
    with a new triple built from provided parts.

    With `check_exist=True`, the write is checked: a receipt written by the same update
    proves that its `WHERE` matched. A normal return means that the store evaluated the
    precondition as true and committed the change. The store isolates commits only (read
    committed): another writer can commit between the evaluation of the precondition and the
    commit of this write. An invariant that must hold under concurrent writers belongs in a
    SHACL shape, which the store checks at the commit.

    The precondition and the removal see the explicit triples of the target graph only:
    `named_graph`, or the default graph without the named graphs. An old triple that is only
    inferred fails the precondition. A triple that is both explicit and inferred stays
    visible after a delete, because a delete clears only the explicit flag.

    Args:
        old_triple (TripleLike): Existing triple to update.
        new_triple (Optional[PartialTripleLike]): Replacement values (subject/predicate/object). Use this
            or `new_sub`/`new_pred`/`new_obj`.
        new_sub (Optional[SubjectLike]): Replacement subject.
        new_pred (Optional[PredicateLike]): Replacement predicate.
        new_obj (Optional[ObjectLike]): Replacement object.
        check_exist (Optional[bool]): If True, the precondition is that `old_triple` exists.
            Defaults to True. If False, no receipt is written: the update still applies only
            when `old_triple` matches its `WHERE`, and returns True either way.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.

    Returns:
        bool: True. A false precondition raises instead of returning False.

    Raises:
        PreconditionFailedError: `old_triple` was not an explicit triple of the target graph,
            and nothing was written. Its `.triples` is `[old_triple]`.
        InvalidInputError: If neither or both of `new_triple` and any of `new_sub`/`new_pred`/`new_obj` are provided,
            or if input triples are incomplete/invalid.
    """
    elems_given = new_sub is not None or new_pred is not None or new_obj is not None
    if (new_triple and elems_given) or (not new_triple and not elems_given):
        raise InvalidInputError(
            "Either 'new triple' or 'new_sub/new_pred/new_obj' must be provided, not both."
        )

    old_triple = utils.sanitize_triple(old_triple)
    new_triple = utils.sanitize_triple(
        new_triple or (new_sub, new_pred, new_obj),
        allow_partial=True,
    )

    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph

    # Determine replacement variables
    update_triple = tuple(n if n else o for o, n in zip(old_triple, new_triple))

    if check_exist:
        return checked_write.checked_write(
            self,
            operation="triple_update",
            old_triples=[old_triple],
            new_triples=[update_triple],
            named_graph=named_graph,
            precondition="the old triple exists",
            named_triples=[old_triple],
        )

    query = SPARQLQuery.delete_insert_data(
        delete_triples=[old_triple],
        insert_triples=[update_triple],
        where_clauses=[utils.triple_to_string(old_triple, ".")],
        named_graph=named_graph,
    )
    self.query(query=query, update=True)

    self.logger.debug(
        f"Successfully updated triple to: ({utils.triple_to_string(update_triple)}), named_graph: {named_graph or "default"}, repository: {self._repository}"
    )
    return True
