from requests import Response
from typing import TYPE_CHECKING, Optional
from rdflib import Graph
from kapps_triplestore_interface.exceptions import (
    GraphDbException,
    ShaclValidationError,
)
from kapps_triplestore_interface.utils.iri import IRI
from kapps_triplestore_interface.utils.types import GraphNameLike

if TYPE_CHECKING:
    from kapps_triplestore_interface import GraphDB


def fetch_statements(
    self: "GraphDB",
    graph_iri: Optional[GraphNameLike] = None,
) -> Optional[Graph]:
    """
    Fetch statements from a named or the default graph.

    Queries the RDF4J Graph Store endpoint and parses the response into an
    `rdflib.Graph`. When `graph_iri` is None, the default graph is fetched.

    Args:
        graph_iri (Optional[GraphNameLike]): The named graph IRI to fetch; when
            None, the default graph is fetched.

    Returns:
        Optional[Graph]: The parsed graph on success; `None` when the request fails.

    Raises:
        requests.exceptions.RequestException: If the underlying HTTP request fails.
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
    )

    if response.status_code != 200:
        self.logger.warning(
            f"Failed to fetch named graph: {response.status_code} - {response.text}"
            if graph_iri_str
            else f"Failed to fetch default graph: {response.status_code} - {response.text}"
        )
        return None

    self.logger.debug(
        f"Named graph '{graph_iri_str}' fetched successfully!"
        if graph_iri_str
        else "Default graph fetched successfully!"
    )
    g.parse(data=response.text, format="nt")
    return g


def import_statements(
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

    Args:
        content (str): RDF content to import.
        overwrite (Optional[bool]): Use PUT to overwrite existing content. Defaults to False.
        graph_iri (Optional[GraphNameLike]): Target named graph IRI; default graph when None.
        content_type (Optional[str]): MIME type of `content` (e.g., 'application/x-turtle').
            Defaults to 'application/x-turtle'.

    Returns:
        bool: True on success (HTTP 204), False otherwise.

    Raises:
        requests.exceptions.RequestException: If the underlying HTTP request fails.
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
        self.logger.warning(
            f"Failed to import statements to named graph: {response.status_code} - {response.text}"
            if graph_iri_str
            else f"Failed to import statements to default graph: {response.status_code} - {response.text}"
        )
        return False

    self.logger.debug(
        f"Named graph {graph_iri_str} imported successfully!"
        if graph_iri_str
        else "Default graph imported successfully!"
    )
    return True


def clear_graph(
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
        GraphDbException: If the store answers with any other status than 204. It is
            logged at ERROR. The message names the repository and the graph.
        requests.exceptions.RequestException: If the underlying HTTP request fails.
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
            _carries_validation_report,
        )

        target = f"graph <{graph_iri_str}>" if graph_iri_str else "the default graph"
        message = (
            f"Failed to clear {target} in repository '{self._repository}'"
            f" ({response.status_code}) - {response.text}"
        )
        if _carries_validation_report(response):
            # As in `query()`: the caller decides how loud a refusal is.
            self.logger.debug(message)
            raise ShaclValidationError(message, report=response.text)
        self.logger.error(message)
        raise GraphDbException(message)

    self.logger.debug(
        f"Named graph {graph_iri_str} cleared successfully!"
        if graph_iri_str
        else "Default graph cleared successfully!"
    )
    return True
