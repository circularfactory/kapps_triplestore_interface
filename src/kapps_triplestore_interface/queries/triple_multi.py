# To be imported into ..graph_db.py GraphDB class

from typing import List, Union, Any, Optional, Tuple, TYPE_CHECKING
from rdflib import BNode, Literal
from kapps_triplestore_interface.queries import checked_write
from kapps_triplestore_interface.utils import utils
from kapps_triplestore_interface.utils.iri import IRI
from kapps_triplestore_interface.utils.types import (
    Subject,
    Predicate,
    PartialTripleLike,
    SubjectLike,
    PredicateLike,
    ObjectLike,
    GraphNameLike,
    TriplesLike,
)
from kapps_triplestore_interface.exceptions import InvalidInputError

from kapps_triplestore_interface.sparql_query import SPARQLQuery

if TYPE_CHECKING:
    from kapps_triplestore_interface import GraphDB


def triples_get(
    self: "GraphDB",
    triple: Optional[PartialTripleLike] = None,
    sub: Optional[SubjectLike] = None,
    pred: Optional[PredicateLike] = None,
    obj: Optional[ObjectLike] = None,
    include_explicit: Optional[bool] = True,
    include_implicit: Optional[bool] = True,
    named_graph: Optional[GraphNameLike] = None,
) -> List[Tuple[Subject, Predicate, Any]]:
    """
    Retrieve triples matching any combination of subject, predicate, or object.

    Args:
        triple (Optional[PartialTripleLike]): Combined (subject, predicate, object) filter tuple. Use this
            or individual `sub`/`pred`/`obj`.
        sub (Optional[SubjectLike]): Subject filter (IRI/shorthand/string).
        pred (Optional[PredicateLike]): Predicate filter (IRI/shorthand/string).
        obj (Optional[ObjectLike]): Object filter (IRI/shorthand/Literal/string).
        include_explicit (Optional[bool]): Include explicit triples. Defaults to True.
        include_implicit (Optional[bool]): Include inferred triples. Defaults to True.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.

    Returns:
        List[Tuple[Subject, Predicate, Any]]: Matching triples as `(subject, predicate, object)`, where the
        object is converted to an appropriate Python type when applicable.

    Raises:
        InvalidInputError: If neither or both of `triple` and any of `sub`/`pred`/`obj` are provided.
    """

    elems_given = sub is not None or pred is not None or obj is not None
    if (triple and elems_given) or (not triple and not elems_given):
        raise InvalidInputError(
            "Either 'triple' or 'sub/pred/obj' must be provided, not both."
        )

    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph
    if named_graph is not None and not hasattr(named_graph, "n3"):
        named_graph = IRI(named_graph)

    sub, pred, obj = utils.sanitize_triple(
        triple or (sub, pred, obj), allow_partial=True
    )

    binds = []
    filter = []

    def _append_bind_and_filter(
        var: str,
        value: Union[IRI, BNode, Literal],
    ) -> None:
        if isinstance(value, (IRI, BNode)):
            binds.append(f"BIND({value.n3()} AS {var})")
        elif isinstance(value, Literal):
            filter.append(f"FILTER(?o={value.n3()})")
        else:
            raise Exception(
                f"Value must be either IRI or Literal, is type {type(value)}"
            )

    if sub is not None:
        _append_bind_and_filter("?s", sub)

    if pred is not None:
        _append_bind_and_filter("?p", pred)

    if obj is not None:
        _append_bind_and_filter("?o", obj)

    query = SPARQLQuery.select(
        variables=["?s", "?p", "?o"],
        where_clauses=binds + ["?s ?p ?o ."] + filter,
        named_graph=named_graph,
        include_explicit=include_explicit,
        include_implicit=include_implicit,
    )
    results = self.query(
        query=query.to_string(validate=False), convert_bindings=True
    )

    converted_results = [
        (result["s"], result["p"], result["o"])
        for result in results["results"]["bindings"]
    ]

    return converted_results


def any_triple_exists(
    self: "GraphDB",
    triples: TriplesLike,
    named_graph: Optional[GraphNameLike] = None,
) -> bool:
    """
    Check if any of the given triples exist.

    Args:
        triples (TriplesLike): Triples to check.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.

    Returns:
        bool: True if at least one exists, False otherwise.

    Raises:
        InvalidInputError: If `triples` is empty.
        TripleStoreResponseError: If the store answers with an error status. A failure is never
            read as False.
        TripleStoreUnavailableError: If the store gives no answer.
    """
    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph

    if not triples:
        raise InvalidInputError(f"Cannot check existence of empty triple list.")

    validated_triples = [utils.sanitize_triple(triple) for triple in triples]

    triple_groups = utils.group_triples_by_bnode(validated_triples)

    # Build UNION patterns for ASK query
    union_patterns = []
    for group in triple_groups:
        group_pattern = " .\n    ".join(
            utils.triple_to_string(triple, "") for triple in group
        )
        union_patterns.append(f"{{\n    {group_pattern} .\n  }}")

    where_clause = "\n  UNION\n  ".join(union_patterns)

    query = SPARQLQuery.ask(
        where_clauses=[where_clause],
        named_graph=named_graph,
    )
    ask_result = self.query(query=query.to_string(validate=False), update=False)

    if ask_result["boolean"] is True:
        self.logger.debug(
            f"At least one of the triples exists, named_graph: {named_graph or 'default'}, repository: {self._repository}"
        )
        return True

    self.logger.debug(
        f"None of the triples exists, named_graph: {named_graph or 'default'}, repository: {self._repository}"
    )
    return False


def all_triple_exists(
    self: "GraphDB",
    triples: TriplesLike,
    named_graph: Optional[GraphNameLike] = None,
) -> bool:
    """
    Check if all of the given triples exist.

    Args:
        triples (TriplesLike): Triples to check.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.

    Returns:
        bool: True if all exist, False otherwise.

    Raises:
        InvalidInputError: If `triples` is empty.
        TripleStoreResponseError: If the store answers with an error status. A failure is never
            read as False.
        TripleStoreUnavailableError: If the store gives no answer.
    """
    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph

    if not triples:
        raise InvalidInputError(f"Cannot check existence of empty triple list.")

    triple_strings = []
    for triple in triples:
        triple = utils.sanitize_triple(triple)
        triple_strings.append(utils.triple_to_string(triple, "."))

    query = SPARQLQuery.ask(
        where_clauses=triple_strings,
        named_graph=named_graph,
    )
    ask_result = self.query(query=query.to_string(validate=False), update=False)

    if ask_result["boolean"] is False:
        self.logger.debug(
            f"Not all of the triples exist: ({triple_strings}), named_graph: {named_graph or "default"}, repository: {self._repository}"
        )
        return False

    self.logger.debug(
        f"All of the triples exist: ({triple_strings}), named_graph: {named_graph or "default"}, repository: {self._repository}"
    )
    return True


def triples_add(
    self: "GraphDB",
    triples_to_add: TriplesLike,
    check_exist: Optional[bool] = True,
    named_graph: Optional[GraphNameLike] = None,
    absent_subjects: Optional[List[SubjectLike]] = None,
) -> bool:
    """
    Add multiple triples to the graph database.

    With `check_exist=True` or `absent_subjects`, the write is checked: its precondition and
    the insert are one update request, and a receipt written by the same update proves that
    it was applied. A normal return means that the store evaluated the precondition as true
    and committed the change. The store isolates commits only (read committed): another
    writer can commit between the evaluation of the precondition and the commit of this
    write. An invariant that must hold under concurrent writers belongs in a SHACL shape,
    which the store checks at the commit.

    The precondition sees the explicit triples of the target graph only: `named_graph`, or
    the default graph without the named graphs. Inferred triples do not count, so a triple
    that is only inferred is added as an explicit triple. A triple that is both explicit and
    inferred stays visible after a delete, because a delete clears only the explicit flag.

    Args:
        triples_to_add (TriplesLike): Triples to add.
        check_exist (Optional[bool]): If True, the precondition is that none of the triples
            exists yet. Triples that share a blank node count as one structure. Defaults to True.
            If False and `absent_subjects` is not given, the triples are inserted unchecked:
            existing ones are a no-op, and the rest are added.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.
        absent_subjects (Optional[List[SubjectLike]]): IRIs that must not yet be the subject of
            any explicit triple in the target graph. A subject that occurs only as an object
            (a forward reference) passes. Adds to the precondition, also with `check_exist=False`.

    Returns:
        bool: True. A false precondition raises instead of returning False. An empty
        `triples_to_add` sends no request and returns True.

    Raises:
        PreconditionFailedError: The precondition was false, and nothing was written. Its
            `.triples` are `triples_to_add` (with `check_exist=True`), followed by
            `(subject, None, None)` for each of `absent_subjects`.
        InvalidInputError: A triple or an absent subject is invalid.
    """
    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph

    if not triples_to_add:
        return True

    validated_triples_to_add = [
        utils.sanitize_triple(triple) for triple in triples_to_add
    ]
    subjects = checked_write.sanitize_absent_subjects(absent_subjects)

    if check_exist or subjects:
        filters = []
        named_triples = []
        conditions = []
        if check_exist:
            filters.append(checked_write.none_exist_filter(validated_triples_to_add))
            named_triples.extend(validated_triples_to_add)
            conditions.append("none of the triples exists yet")
        filters.extend(
            checked_write.absent_subject_filter(subject, index)
            for index, subject in enumerate(subjects, start=1)
        )
        named_triples.extend((subject, None, None) for subject in subjects)
        if subjects:
            conditions.append("no absent subject has a triple")
        return checked_write.checked_write(
            self,
            operation="triples_add",
            old_triples=[],
            new_triples=validated_triples_to_add,
            named_graph=named_graph,
            precondition=" and ".join(conditions),
            named_triples=named_triples,
            filters=filters,
        )

    triple_strings = [
        utils.triple_to_string(triple, ".") for triple in validated_triples_to_add
    ]

    query = SPARQLQuery.insert_data(
        triples=validated_triples_to_add,
        named_graph=named_graph,
    )
    self.query(query=query.to_string(validate=False), update=True)

    self.logger.debug(
        f"Successfully added triples: ({triple_strings}), named_graph: {named_graph or "default"}, repository: {self._repository}"
    )
    return True


def triples_delete(
    self: "GraphDB",
    triples_to_delete: TriplesLike,
    check_exist: Optional[bool] = True,
    named_graph: Optional[GraphNameLike] = None,
) -> bool:
    """
    Delete multiple triples from the graph database.

    With `check_exist=True`, the write is checked: its precondition and the delete are one
    update request, and a receipt written by the same update proves that it was applied. A
    normal return means that the store evaluated the precondition as true and committed the
    change. The store isolates commits only (read committed): another writer can commit
    between the evaluation of the precondition and the commit of this write. An invariant
    that must hold under concurrent writers belongs in a SHACL shape, which the store checks
    at the commit.

    The precondition and the delete see the explicit triples of the target graph only:
    `named_graph`, or the default graph without the named graphs. A delete cannot remove an
    inferred triple, so a triple that is only inferred fails the precondition. A triple that
    is both explicit and inferred stays visible after a delete, because a delete clears only
    the explicit flag.

    Args:
        triples_to_delete (TriplesLike): Triples to delete.
        check_exist (Optional[bool]): If True, the precondition is that all of the triples
            exist. Defaults to True. If False, the triples are deleted unchecked: missing ones
            are a no-op, and without a named graph the delete acts on every graph.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.

    Returns:
        bool: True. A false precondition raises instead of returning False. An empty
        `triples_to_delete` sends no request and returns True.

    Raises:
        PreconditionFailedError: At least one triple was not an explicit triple of the target
            graph, and nothing was deleted. Its `.triples` are `triples_to_delete`.
    """
    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph

    if not triples_to_delete:
        return True

    validated_triples_to_delete = [
        utils.sanitize_triple(triple) for triple in triples_to_delete
    ]

    if check_exist:
        return checked_write.checked_write(
            self,
            operation="triples_delete",
            old_triples=validated_triples_to_delete,
            new_triples=[],
            named_graph=named_graph,
            precondition="all of the triples exist",
            named_triples=validated_triples_to_delete,
        )

    triple_strings = [
        utils.triple_to_string(triple, ".") for triple in validated_triples_to_delete
    ]

    query = SPARQLQuery.delete_data(
        triples=validated_triples_to_delete,
        named_graph=named_graph,
    )
    self.query(query=query.to_string(validate=False), update=True)

    self.logger.debug(
        f"Successfully deleted triples: ({triple_strings}), named_graph: {named_graph or "default"}, repository: {self._repository}"
    )
    return True


def triples_update(
    self: "GraphDB",
    old_triples: TriplesLike,
    new_triples: TriplesLike,
    check_exist: Optional[bool] = True,
    named_graph: Optional[GraphNameLike] = None,
    absent_subjects: Optional[List[SubjectLike]] = None,
) -> bool:
    """
    Update multiple RDF triples in the triplestore.

    The removal of `old_triples` and the insertion of `new_triples` are applied in a
    single atomic `DELETE ... INSERT ... WHERE` SPARQL transaction. The two lists need
    not be the same length: this supports pure additions, pure removals, and general
    replacements. Atomicity matters for constraint (e.g. SHACL) correctness — replacing
    a cardinality-constrained property (such as a possession handover under a
    "possessed by exactly one resource" shape) must never expose the intermediate state
    in which the property is momentarily absent.

    With `check_exist=True` or `absent_subjects`, the write is checked: a receipt written by
    the same update proves that its `WHERE` matched. A normal return means that the store
    evaluated the precondition as true and committed the change. The store isolates commits
    only (read committed): another writer can commit between the evaluation of the
    precondition and the commit of this write. An invariant that must hold under concurrent
    writers belongs in a SHACL shape, which the store checks at the commit.

    The precondition and the removal see the explicit triples of the target graph only:
    `named_graph`, or the default graph without the named graphs. An old triple that is only
    inferred fails the precondition. A triple that is both explicit and inferred stays
    visible after a delete, because a delete clears only the explicit flag.

    Args:
        old_triples (TriplesLike): Triples to remove.
        new_triples (TriplesLike): Triples to insert. Need not match the length of `old_triples`.
        check_exist (Optional[bool]): If True, the precondition is that all old triples exist.
            Defaults to True. If False and `absent_subjects` is not given, no receipt is
            written: the update still applies only when the old triples match its `WHERE`,
            and returns True either way.
        named_graph (Optional[GraphNameLike]): Override the client's default named graph.
        absent_subjects (Optional[List[SubjectLike]]): IRIs that must not yet be the subject of
            any explicit triple in the target graph. A subject that occurs only as an object
            (a forward reference) passes. Adds to the precondition. With it, the write is
            checked also when `check_exist=False`, and the old triples are part of the
            precondition, because they are always part of the `WHERE`.

    Returns:
        bool: True. A false precondition raises instead of returning False. Two empty lists
        send no request and return True.

    Raises:
        PreconditionFailedError: The precondition was false, and nothing was written. Its
            `.triples` are `old_triples`, followed by `(subject, None, None)` for each of
            `absent_subjects`.
        InvalidInputError: A triple or an absent subject is invalid.
    """
    named_graph = IRI(named_graph) if named_graph is not None else self.named_graph

    if not old_triples and not new_triples:
        return True

    validated_old_triples = [utils.sanitize_triple(triple) for triple in old_triples]
    validated_new_triples = [utils.sanitize_triple(triple) for triple in new_triples]
    subjects = checked_write.sanitize_absent_subjects(absent_subjects)

    if check_exist or subjects:
        conditions = []
        if validated_old_triples:
            conditions.append("all old triples exist")
        if subjects:
            conditions.append("no absent subject has a triple")
        return checked_write.checked_write(
            self,
            operation="triples_update",
            old_triples=validated_old_triples,
            new_triples=validated_new_triples,
            named_graph=named_graph,
            precondition=" and ".join(conditions) or "none",
            named_triples=validated_old_triples
            + [(subject, None, None) for subject in subjects],
            filters=[
                checked_write.absent_subject_filter(subject, index)
                for index, subject in enumerate(subjects, start=1)
            ],
        )

    query = checked_write.render_update(
        validated_old_triples, validated_new_triples, named_graph
    )
    self.query(query=query, update=True)

    self.logger.debug(
        f"Successfully updated triples ({validated_old_triples}) -> ({validated_new_triples}), named_graph: {named_graph or "default"}, repository: {self._repository}"
    )
    return True
