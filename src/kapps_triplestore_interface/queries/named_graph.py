# To be imported into ..graph_db.py GraphDB class

from typing import List, TYPE_CHECKING
from kapps_triplestore_interface import _deprecation
from kapps_triplestore_interface.utils.types import GraphNameLike

if TYPE_CHECKING:
    from kapps_triplestore_interface import GraphDB


def graphs_get(
    self: "GraphDB",
) -> List[GraphNameLike]:
    """
    Get the list of named graphs in the dataset.

    Returns:
        List[IRI]: List of named graph IRIs. Can be an empty list.

    Raises:
        TripleStoreResponseError: If the store answers with an error status.
        TripleStoreUnavailableError: If the store gives no answer.
    """
    # TODO: This query is quite slow and should be optimized
    # SPARQL query to retrieve all named graphs

    query = """
SELECT DISTINCT ?graph WHERE {
    GRAPH ?graph { ?s ?p ?o }
}
    """
    results = self.query(query, convert_bindings=True)
    return [result["graph"] for result in results["results"]["bindings"]]


@_deprecation.renamed("graphs_get")
def get_list_of_named_graphs(
    self: "GraphDB",
) -> List[GraphNameLike]:
    """The deprecated name of `graphs_get`."""
    return self.graphs_get()
