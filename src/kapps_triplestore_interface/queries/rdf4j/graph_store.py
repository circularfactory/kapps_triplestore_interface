"""The Graph Store verbs: `graph_get`, `graph_add` and `graph_clear`.

They follow the operations of the SPARQL 1.1 Graph Store HTTP Protocol: `graph_get` is its GET,
`graph_add` its POST (or PUT, to overwrite) and `graph_clear` its DELETE. GraphDB serves them at
the RDF4J endpoint `rdf-graphs/service` of a repository.
"""

from requests import Response
from typing import TYPE_CHECKING, Optional
from rdflib import Graph
from kapps_triplestore_interface import _deprecation
from kapps_triplestore_interface.utils.iri import IRI
from kapps_triplestore_interface.utils.types import GraphNameLike

if TYPE_CHECKING:
    from kapps_triplestore_interface import GraphDB


def graph_get(
    self: "GraphDB",
    graph_iri: Optional[GraphNameLike] = None,
) -> Graph:
    """
    Fetch statements from a named or the default graph.

    Queries the RDF4J Graph Store endpoint and parses the response into an
    `rdflib.Graph`. When `graph_iri` is None, the default graph is fetched.

    Args:
        graph_iri (Optional[GraphNameLike]): The named graph IRI to fetch; when
            None, the default graph is fetched.

    Returns:
        Graph: The parsed graph. An error answer raises instead.

    Raises:
        AuthenticationError: If the store answers 401.
        TripleStoreAccessError: If the store answers 403.
        TripleStoreResponseError: If the store answers with any other status than 200. It is
            logged at ERROR. The message names the repository and the graph.
        TripleStoreUnavailableError: If the request gets no answer. When the store closed the
            connection without an answer, the read is sent once more, on a fresh connection,
            and raises only if that fails as well.
    """
    graph_iri_str = (
        str(IRI(graph_iri)) if graph_iri else "http://www.openrdf.org/schema/sesame#nil"
    )
    g = Graph()
    endpoint = f"repositories/{self._repository}/rdf-graphs/service"

    response: Response = self._make_request(
        "get",
        endpoint,
        params={"graph": graph_iri_str},
        headers={"Content-Type": "application/x-turtle"},
        retry_after_idle_close=True,
    )

    if response.status_code != 200:
        # `query()`'s mapping of an error answer to a type. Imported here, not at the top:
        # `graph_db` imports this module while it defines `GraphDB`.
        from kapps_triplestore_interface.graph_db import (  # pylint: disable=import-outside-toplevel
            _raise_error_answer,
        )

        target = f"graph <{graph_iri_str}>" if graph_iri else "the default graph"
        _raise_error_answer(
            self.logger,
            response,
            f"Failed to fetch {target} in repository '{self._repository}'",
        )

    self.logger.debug(
        f"Named graph '{graph_iri_str}' fetched successfully!"
        if graph_iri_str
        else "Default graph fetched successfully!"
    )
    g.parse(data=response.text, format="nt")
    return g


def graph_add(
    self: "GraphDB",
    content: str,
    overwrite: Optional[bool] = False,
    graph_iri: Optional[GraphNameLike] = None,
    content_type: Optional[str] = "application/x-turtle",
) -> bool:
    """
    Import RDF statements into a named or the default graph.

    Sends content to the RDF4J Graph Store endpoint using POST (append) or PUT
    (overwrite). When `graph_iri` is None, the default graph is targeted.

    A normal return means that the store accepted the import. Any other answer raises. A store
    with SHACL validation can refuse an import, because the data would violate a shape. It then
    imports nothing.

    Args:
        content (str): RDF content to import.
        overwrite (Optional[bool]): Use PUT to overwrite existing content. Defaults to False.
        graph_iri (Optional[GraphNameLike]): Target named graph IRI; default graph when None.
        content_type (Optional[str]): MIME type of `content` (e.g., 'application/x-turtle').
            Defaults to 'application/x-turtle'.

    Returns:
        bool: True on success (HTTP 204). Any other answer raises.

    Raises:
        ShaclValidationError: If the store refused the import because the data would violate
            a SHACL shape. Its `report` is the store's validation report. The refusal is
            logged only at DEBUG; the caller decides how loud it is.
        AuthenticationError: If the store answers 401, also after one new login.
        TripleStoreAccessError: If the store answers 403.
        TripleStoreResponseError: If the store answers with any other status than 204. It is
            logged at ERROR, as are the two above. The message names the repository and the
            graph.
        TripleStoreUnavailableError: If the request gets no answer. The import is not sent
            again.
    """
    graph_iri_str = str(IRI(graph_iri)) if graph_iri else None
    if graph_iri_str:
        endpoint = f"repositories/{self._repository}/rdf-graphs/service"
    else:
        endpoint = f"repositories/{self._repository}/rdf-graphs/service?default"

    method = "put" if overwrite else "post"

    response: Response = self._make_request(
        method,
        endpoint,
        params={"graph": graph_iri_str} if graph_iri_str else None,
        headers={"Content-Type": content_type},
        data=content,
    )

    if response.status_code != 204:
        # `query()`'s mapping of an error answer to a type. Imported here, not at the top:
        # `graph_db` imports this module while it defines `GraphDB`.
        from kapps_triplestore_interface.graph_db import (  # pylint: disable=import-outside-toplevel
            _raise_error_answer,
        )

        target = f"graph <{graph_iri_str}>" if graph_iri_str else "the default graph"
        _raise_error_answer(
            self.logger,
            response,
            f"Failed to import into {target} in repository '{self._repository}'",
        )

    self.logger.debug(
        f"Named graph {graph_iri_str} imported successfully!"
        if graph_iri_str
        else "Default graph imported successfully!"
    )
    return True


def graph_clear(
    self: "GraphDB",
    graph_iri: Optional[GraphNameLike] = None,
) -> bool:
    """
    Clear a named graph or the default graph.

    Deletes the specified named graph from the triplestore; when `graph_iri` is
    None, clears the default graph.

    A store with SHACL validation can refuse a clear, because the remaining data would
    violate a shape. It then clears nothing.

    Args:
        graph_iri (Optional[GraphNameLike]): IRI of the named graph to clear;
            default graph when None.

    Returns:
        bool: True on success (HTTP 204). Any other answer raises.

    Raises:
        ShaclValidationError: If the store refused the clear because the remaining data
            would violate a SHACL shape. Its `report` is the store's validation report. The
            refusal is logged only at DEBUG; the caller decides how loud it is.
        AuthenticationError: If the store answers 401.
        TripleStoreAccessError: If the store answers 403.
        TripleStoreResponseError: If the store answers with any other status than 204. It is
            logged at ERROR, as are the two above. The message names the repository and the
            graph.
        TripleStoreUnavailableError: If the request gets no answer. The clear is not sent
            again.
    """
    graph_iri_str = str(IRI(graph_iri)) if graph_iri else None
    if graph_iri_str:
        endpoint = f"repositories/{self._repository}/rdf-graphs/service"
    else:
        endpoint = f"repositories/{self._repository}/rdf-graphs/service?default"

    response: Response = self._make_request(
        "delete",
        endpoint,
        params={"graph": graph_iri_str} if graph_iri_str else None,
    )

    if response.status_code != 204:
        # `query()`'s mapping of an error answer to a type. Imported here, not at the top:
        # `graph_db` imports this module while it defines `GraphDB`.
        from kapps_triplestore_interface.graph_db import (  # pylint: disable=import-outside-toplevel
            _raise_error_answer,
        )

        target = f"graph <{graph_iri_str}>" if graph_iri_str else "the default graph"
        _raise_error_answer(
            self.logger,
            response,
            f"Failed to clear {target} in repository '{self._repository}'",
        )

    self.logger.debug(
        f"Named graph {graph_iri_str} cleared successfully!"
        if graph_iri_str
        else "Default graph cleared successfully!"
    )
    return True


# The deprecated names. Each call emits one `DeprecationWarning` that names the successor, and
# then runs the successor: the behaviour lives in one function.


@_deprecation.renamed("graph_get")
def fetch_statements(
    self: "GraphDB",
    graph_iri: Optional[GraphNameLike] = None,
) -> Graph:
    """The deprecated name of `graph_get`."""
    return self.graph_get(graph_iri)


@_deprecation.renamed("graph_add")
def import_statements(
    self: "GraphDB",
    content: str,
    overwrite: Optional[bool] = False,
    graph_iri: Optional[GraphNameLike] = None,
    content_type: Optional[str] = "application/x-turtle",
) -> bool:
    """The deprecated name of `graph_add`."""
    return self.graph_add(
        content, overwrite=overwrite, graph_iri=graph_iri, content_type=content_type
    )


@_deprecation.renamed("graph_clear")
def clear_graph(
    self: "GraphDB",
    graph_iri: Optional[GraphNameLike] = None,
) -> bool:
    """The deprecated name of `graph_clear`."""
    return self.graph_clear(graph_iri)
