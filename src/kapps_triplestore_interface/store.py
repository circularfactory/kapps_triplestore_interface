"""The contract of a store, and where a store is.

The layers above the interface type a store as `TripleStore`, and they build one with
`connect()`, from a `TripleStoreEndpoint` and an auth provider. They never name the class of a
store's adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, Union

from rdflib import Graph, Namespace

from kapps_triplestore_interface import _environment
from kapps_triplestore_interface.exceptions import TripleStoreNotSupportedError
from kapps_triplestore_interface.sparql_query import SPARQLQuery
from kapps_triplestore_interface.utils.iri import IRI
from kapps_triplestore_interface.utils.types import (
    GraphNameLike,
    IRILike,
    ObjectLike,
    PartialTripleLike,
    Predicate,
    PredicateLike,
    Subject,
    SubjectLike,
    TripleLike,
    TriplesLike,
)


class TripleStore(Protocol):
    """A store, as the layers above the interface use it.

    It declares each operation that the layers above call on a store, and no other. The GraphDB
    adapter, `GraphDB`, implements it; each operation is documented there. A test double
    implements it without inheriting from it.

    - Reads: `query`, `triple_exists`, `triples_get`, `iri_exists`, `is_subclass`,
      `owl_get_classes_of_individual`, `graph_get`.
    - Writes: `triple_add`, `triple_delete`, `triples_add`, `triples_delete`,
      `triples_update`, `graph_add`, `graph_clear`, and `query` with `update=True`.
    - Names: `new_iri`.
    - The store's registries, which SPARQL does not cover: the dataset's prefixes,
      `prefixes_get`, `prefix_set` and `prefix_delete`, its SHACL shapes, `shapes_set`, and
      the validation of the whole dataset against a shapes document, `validate`.
    - The store itself: its `dataset`, and `close`.

    A store that has no such registry raises `TripleStoreNotSupportedError` for its
    operations, and they are never a silent no-op. An adapter that inherits this type and does
    not implement a registry raises it from the operations declared here.
    """

    @property
    def dataset(self) -> str: ...

    def query(
        self,
        query: Union[SPARQLQuery, str],
        update: Optional[bool] = False,
        convert_bindings: Optional[bool] = False,
    ) -> Union[Dict, bool]: ...

    def triple_exists(
        self,
        triple: TripleLike,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool: ...

    def triple_add(
        self,
        triple: TripleLike,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool: ...

    def triple_delete(
        self,
        triple: TripleLike,
        check_exist: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool: ...

    def triples_get(
        self,
        triple: Optional[PartialTripleLike] = None,
        sub: Optional[SubjectLike] = None,
        pred: Optional[PredicateLike] = None,
        obj: Optional[ObjectLike] = None,
        include_explicit: Optional[bool] = True,
        include_implicit: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
    ) -> List[Tuple[Subject, Predicate, Any]]: ...

    def triples_add(
        self,
        triples_to_add: TriplesLike,
        check_exist: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
        absent_subjects: Optional[List[SubjectLike]] = None,
    ) -> bool: ...

    def triples_delete(
        self,
        triples_to_delete: TriplesLike,
        check_exist: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool: ...

    def triples_update(
        self,
        old_triples: TriplesLike,
        new_triples: TriplesLike,
        check_exist: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
        absent_subjects: Optional[List[SubjectLike]] = None,
    ) -> bool: ...

    def iri_exists(
        self,
        iri: IRILike,
        as_sub: Optional[bool] = False,
        as_pred: Optional[bool] = False,
        as_obj: Optional[bool] = False,
        include_explicit: Optional[bool] = True,
        include_implicit: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool: ...

    def new_iri(
        self,
        base: IRILike,
        schema: Optional[Callable[[IRI], IRI]] = None,
        test_schema: bool = True,
    ) -> IRI: ...

    def is_subclass(
        self,
        subclass_iri: IRILike,
        class_iri: IRILike,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool: ...

    def owl_get_classes_of_individual(
        self,
        instance_iri: IRILike,
        ignored_prefixes: Optional[List[Namespace]] = None,
        local_name: Optional[bool] = False,
        include_explicit: Optional[bool] = True,
        include_implicit: Optional[bool] = False,
        named_graph: Optional[GraphNameLike] = None,
    ) -> List[Union[IRI, str]]: ...

    def graph_get(
        self,
        graph_iri: Optional[GraphNameLike] = None,
    ) -> Graph: ...

    def graph_add(
        self,
        content: str,
        overwrite: Optional[bool] = False,
        graph_iri: Optional[GraphNameLike] = None,
        content_type: Optional[str] = "application/x-turtle",
    ) -> bool: ...

    def graph_clear(
        self,
        graph_iri: Optional[GraphNameLike] = None,
    ) -> bool: ...

    def close(self) -> None: ...

    def prefixes_get(self) -> Dict[str, str]:
        """Each prefix of the dataset, with the namespace IRI that it stands for.

        The empty prefix, if the dataset has one, is the key `""`.

        Raises:
            TripleStoreNotSupportedError: If the store has no prefix registry.
        """
        raise TripleStoreNotSupportedError(_no_registry(self, "prefixes_get", "prefix"))

    def prefix_set(self, prefix: str, iri: str) -> None:
        """Let `prefix` stand for the namespace `iri` in the dataset.

        A prefix that the dataset has already stands for `iri` afterwards. `""` is the empty
        prefix.

        Raises:
            TripleStoreNotSupportedError: If the store has no prefix registry.
        """
        raise TripleStoreNotSupportedError(_no_registry(self, "prefix_set", "prefix"))

    def prefix_delete(self, prefix: str) -> None:
        """Remove `prefix` from the dataset. Every other prefix stays. `""` is the empty prefix.

        Raises:
            TripleStoreNotSupportedError: If the store has no prefix registry.
        """
        raise TripleStoreNotSupportedError(
            _no_registry(self, "prefix_delete", "prefix")
        )

    def shapes_set(self, data: str, content_type: str) -> None:
        """Replace the SHACL shapes that the store validates the dataset against with `data`.

        `content_type` is the media type of `data`, for example `text/turtle`. An empty
        document removes every shape.

        Raises:
            TripleStoreNotSupportedError: If the store has no shapes registry, or the dataset
                has no SHACL validation. The shapes would otherwise be stored as data that
                validates nothing.
        """
        raise TripleStoreNotSupportedError(_no_registry(self, "shapes_set", "shapes"))

    def validate(self, shapes: str, content_type: str) -> str:
        """Validate the whole dataset against `shapes` and return the store's report verbatim.

        `shapes` is a SHACL shapes document of the media type `content_type`, for example
        `text/turtle`. The report is the store's own answer, unchanged; on GraphDB it is Turtle.
        It does not change the dataset or the shapes that the store validates writes against.

        Raises:
            TripleStoreNotSupportedError: If the store has no whole-dataset validation.
        """
        raise TripleStoreNotSupportedError(_no_registry(self, "validate", "validation"))


def _no_registry(store: object, operation: str, registry: str) -> str:
    return f"{type(store).__name__} has no {registry} registry, so it cannot do {operation}."


@dataclass(frozen=True)
class TripleStoreEndpoint:
    """Where a store is: its URL and its dataset. It holds no secret, so it can be logged.

    Args:
        url (str): The base URL of the store, for example `http://localhost:7200`.
        dataset (str): The dataset that the store's operations act on. GraphDB calls it a
            repository.
    """

    url: str
    dataset: str

    @classmethod
    def from_env(cls, dataset: Optional[str] = None) -> TripleStoreEndpoint:
        """The endpoint that the environment names.

        Reads `TRIPLESTORE_URL` and, unless `dataset` is given, `TRIPLESTORE_DATASET`.
        `GRAPHDB_URL` and `GRAPHDB_REPOSITORY` are their deprecated fallbacks: a value read
        from one of them emits a `DeprecationWarning`.

        Args:
            dataset (Optional[str]): The dataset. When given, no variable is read for it.

        Raises:
            ValueError: If a variable is missing. The message names it.
        """
        url = _environment.read("TRIPLESTORE_URL")
        if dataset is None:
            dataset = _environment.read("TRIPLESTORE_DATASET")
        return cls(url=url, dataset=dataset)
