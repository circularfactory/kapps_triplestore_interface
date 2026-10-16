import sys
import warnings
from typing import TYPE_CHECKING, Any

from .sparql_query import SPARQLQuery
from .graph_db import GraphDB
from .store import TripleStore, TripleStoreEndpoint
from .auth import BasicAuth, GDBTokenAuth
from .connection import connect
from .utils import graph_db_credentials as _graph_db_credentials
from .utils.iri import IRI
from .utils.utils import to_literal
from .utils.processing import process_bindings_select
from .utils.pretty_print import format_result
from .kafka.kafka_manager import KafkaManager
from .utils.xsd_typemap import XSDToPythonTypes, XSDToPythonMapper
from .exceptions import (
    ShaclValidationError,
    PreconditionFailedError,
    TripleStoreResponseError,
    TripleStoreUnavailableError,
    AuthenticationError,
    TripleStoreAccessError,
    TripleStoreNotSupportedError,
)

__all__ = [
    "connect",
    "TripleStore",
    "TripleStoreEndpoint",
    "BasicAuth",
    "GDBTokenAuth",
    "GraphDB",
    "GraphDBCredentials",
    "IRI",
    "SPARQLQuery",
    "to_literal",
    "process_bindings_select",
    "format_result",
    "KafkaManager",
    "XSDToPythonTypes",
    "XSDToPythonMapper",
    "ShaclValidationError",
    "PreconditionFailedError",
    "TripleStoreResponseError",
    "TripleStoreUnavailableError",
    "AuthenticationError",
    "TripleStoreAccessError",
    "TripleStoreNotSupportedError",
]

if TYPE_CHECKING:
    # A type checker reads the deprecated name as the class. The `as` form re-exports it.
    from .utils.graph_db_credentials import (  # pylint: disable=useless-import-alias
        GraphDBCredentials as GraphDBCredentials,
    )


def __getattr__(name: str) -> Any:
    # `GraphDBCredentials` is a deprecated name, so it is not an attribute of the package: each
    # use of it comes here and warns, also `import *`, because `__all__` still names it.
    if name != "GraphDBCredentials":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # `from kapps_triplestore_interface import GraphDBCredentials` comes here twice: the import
    # machinery first checks that the package has the name, then the import reads it. Only the
    # read is the caller's use, so only the read warns.
    if not sys._getframe(1).f_code.co_filename.startswith("<frozen importlib"):
        warnings.warn(
            _graph_db_credentials._DEPRECATION, DeprecationWarning, stacklevel=2
        )
    return _graph_db_credentials._GraphDBCredentials
