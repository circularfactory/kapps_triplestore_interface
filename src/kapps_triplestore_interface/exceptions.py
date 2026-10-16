"""The errors of the interface.

Each type tells the caller one action, and its docstring names it:

- **Repair:** the tool or its deployment is broken, for example the configuration, the
  credentials or the rights. The operator acts. Do not send the request again before the repair.
- **Retry:** this attempt failed for a temporary reason. Send the request again later.
- **Refresh:** the caller's information is old. Read the state again, then decide.
- **Refused:** the request is correct, but a rule of the domain does not permit it, for
  example a SHACL shape. Do not send it again before the state changes.
- **Fix the call:** the caller used the API incorrectly. Do not send it again.

An error answer of the store raises `TripleStoreResponseError` or one of its subtypes. Its
`status` is the store's HTTP status, and its message holds the store's answer unchanged.

A name that this module deprecates is an alias of the type that replaces it. Each use of the old
name emits one `DeprecationWarning` that names its successor. The changelog lists them.
"""

import warnings
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    # Only for annotations: `utils.iri` imports this module.
    from kapps_triplestore_interface.utils.types import GraphName, PartialTriple


class TripleStoreInterfaceError(Exception):
    """
    Base exception for the triple store interface.

    Serves as the common ancestor for all custom exceptions in this
    package to allow catching them collectively when desired. Each subclass names its action.
    """

    pass


class InvalidDatasetError(TripleStoreInterfaceError):
    """
    The dataset does not exist on the store.

    Action: Repair. Configure a dataset that the store has. GraphDB calls a dataset a
    repository.

    Args:
        message (str): Why the dataset is not available. GraphDB's messages say repository.
    """

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)


class TripleStoreResponseError(TripleStoreInterfaceError):
    """
    The store answered with an error status.

    Action: Repair. This is the action for an error answer that no subtype covers. The subtypes
    name the action of the answers that they cover: `AuthenticationError` (401),
    `TripleStoreAccessError` (403) and `ShaclValidationError` (a SHACL validation report).

    The message holds the store's answer unchanged. `status` is the store's HTTP status.

    Args:
        message (str): The error message. It contains the store's answer unchanged.
        status (Optional[int]): The store's HTTP status, or `None` for an error that was
            constructed without one.
    """

    def __init__(
        self,
        message: str,
        status: Optional[int] = None,
    ):
        self.message = message
        self.status = status
        super().__init__(self.message)


class AuthenticationError(TripleStoreResponseError):
    """
    The store did not accept the credentials (401).

    Action: Repair. Correct the credentials of the client.

    Args:
        message (str): Details about the authentication error, with the store's answer.
        status (Optional[int]): The store's HTTP status, 401 when the store answered.
    """


class TripleStoreAccessError(TripleStoreResponseError):
    """
    The store refused the identity's access to the dataset (403).

    Action: Repair. Give the identity the rights that it needs.

    Args:
        message (str): The error message, with the store's answer.
        status (Optional[int]): The store's HTTP status, 403.
    """


class TripleStoreUnavailableError(TripleStoreInterfaceError):
    """
    The store cannot be reached, it did not answer in time, or the connection dropped.

    Action: Retry. Send the request again later. The error is chained to the transport error:
    `__cause__` is the error of the HTTP client.

    A read whose pooled connection the store closed while idle was already sent again once. The
    interface never sends a write again, because the store may have applied it. A caller's retry
    of a write is safe:

    - A checked write refuses a second application with `PreconditionFailedError`.
    - An insert or an import repeats as a no-op, because a graph is a set. The exceptions are
      blank nodes, which a second insert creates again, and a raw update that the caller writes
      itself.

    Args:
        message (str): Which request got no answer, and the transport error.
    """

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)


class TripleStoreNotSupportedError(TripleStoreInterfaceError):
    """
    The store, or the dataset, cannot do the operation.

    Action: Fix the call. Do not call the operation on this store.

    Args:
        message (str): Which operation the store cannot do.
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

    Action: Fix the call.

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

    Action: Fix the call.

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

    Action: Fix the call.

    Args:
        message (str): Description of the IRI validation failure.
    """

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)


class ShaclValidationError(TripleStoreResponseError):
    """
    The store refused a write, because the data would violate a SHACL shape.

    Action: Refused. Do not send the write again before the state changes.

    A store with SHACL validation checks a write when it commits it. On a violation it commits
    nothing of the write and answers with a validation report.

    Catch this type to tell a refusal from every other failure. Catch
    `TripleStoreInterfaceError` for any error from this package.

    Args:
        message (str): The error message. It contains the HTTP status and the report.
        report (str): The store's validation report, verbatim: the body of its answer.
        status (Optional[int]): The store's HTTP status.
    """

    def __init__(
        self,
        message: str,
        report: str,
        status: Optional[int] = None,
    ):
        self.report = report
        super().__init__(message, status=status)


class PreconditionFailedError(TripleStoreInterfaceError):
    """
    The store found the precondition of a write false, so nothing was written.

    Action: Refresh. Read the state again, then decide.

    A sibling of `TripleStoreResponseError`, not a subclass: the store answered the request
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


# The deprecated names, and the name that replaces each one. A name here is not an attribute of
# the module, so that each use of it goes through `__getattr__` and warns.
_DEPRECATED_ALIASES = {
    "GraphDbException": "TripleStoreResponseError",
    "InvalidRepositoryError": "InvalidDatasetError",
}

if TYPE_CHECKING:
    # A type checker reads an alias as the class, so that an annotation with it stays valid.
    GraphDbException = TripleStoreResponseError
    InvalidRepositoryError = InvalidDatasetError


def __getattr__(name: str) -> Any:
    successor = _DEPRECATED_ALIASES.get(name)
    if successor is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    warnings.warn(
        f"{name} is deprecated; use {successor}, of which it is an alias.",
        DeprecationWarning,
        stacklevel=2,
    )
    return globals()[successor]
