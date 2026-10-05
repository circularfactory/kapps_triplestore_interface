from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    # Only for annotations: `utils.iri` imports this module.
    from kapps_triplestore_interface.utils.types import GraphName, PartialTriple


class TripleStoreInterfaceError(Exception):
    """
    Base exception for the GraphDB interface.

    Serves as the common ancestor for all custom exceptions in this
    package to allow catching them collectively when desired.
    """

    pass


class InvalidRepositoryError(TripleStoreInterfaceError):
    """
    Invalid repository configuration or selection.

    Args:
        message (str): Explanation of why the repository is invalid.
    """

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)


class AuthenticationError(TripleStoreInterfaceError):
    """
    Authentication failure when communicating with GraphDB.

    Args:
        message (str): Details about the authentication error.
    """

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)


class InvalidQueryError(TripleStoreInterfaceError):
    """
    Invalid SPARQL query or update string.

    Args:
        message (str): Description of why the query is invalid.
    """

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)


class InvalidInputError(TripleStoreInterfaceError):
    """
    Invalid input provided to an interface method.

    Args:
        message (str): Explanation of the invalid input condition.
    """

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)


class InvalidIRIError(TripleStoreInterfaceError):
    """
    Invalid IRI value or format encountered.

    Args:
        message (str): Description of the IRI validation failure.
    """

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)


class GraphDbException(TripleStoreInterfaceError):
    """
    General error raised for HTTP or runtime issues with GraphDB.

    Args:
        message (str): The error message returned or constructed for the failure.
    """

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)


class ShaclValidationError(GraphDbException):
    """
    The store refused a write, because the data would violate a SHACL shape.

    A store with SHACL validation checks a write when it commits it. On a violation it commits
    nothing of the write and answers with a validation report.

    Catch this type to tell a refusal from every other failure. Catch
    `TripleStoreInterfaceError` for any error from this package.

    Args:
        message (str): The error message. It contains the HTTP status and the report.
        report (str): The store's validation report, verbatim: the body of its answer.
    """

    def __init__(
        self,
        message: str,
        report: str,
    ):
        self.report = report
        super().__init__(message)


class PreconditionFailedError(TripleStoreInterfaceError):
    """
    The store found the precondition of a write false, so nothing was written.

    A sibling of `GraphDbException`, not a subclass: the store answered the request
    successfully, and the precondition that the interface sent with the write refused it.

    Args:
        message (str): Which write was refused, and why.
        triples (Optional[List[PartialTriple]]): The triples that the precondition named. For a
            delete or an update, the old triples that must exist. For an add, the triples that
            must not exist yet. A subject from `absent_subjects` appears as `(subject, None, None)`.
        named_graph (Optional[GraphName]): The graph the precondition was evaluated in, or `None`
            for the default graph.
    """

    def __init__(
        self,
        message: str,
        triples: Optional[List["PartialTriple"]] = None,
        named_graph: Optional["GraphName"] = None,
    ):
        self.message = message
        self.triples = list(triples) if triples is not None else []
        self.named_graph = named_graph
        super().__init__(self.message)
