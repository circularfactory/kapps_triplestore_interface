"""How a caller gets a working, authenticated store: `connect()`."""

from __future__ import annotations

from kapps_triplestore_interface.auth import BasicAuth, GDBTokenAuth
from kapps_triplestore_interface.graph_db import GraphDB, _probe
from kapps_triplestore_interface.store import TripleStore, TripleStoreEndpoint


def connect(
    endpoint: TripleStoreEndpoint,
    auth: BasicAuth | GDBTokenAuth,
) -> TripleStore:
    """A store at `endpoint`, checked now: it answers, accepts the identity and has the dataset.

    Builds the adapter, makes `auth` log in now, and sends one probe, `ASK {}` on the dataset.
    So a broken configuration fails here, with its type, and not at the first request.

    Args:
        endpoint (TripleStoreEndpoint): The store's URL and dataset.
        auth (BasicAuth | GDBTokenAuth): The auth provider of the identity.

    Returns:
        TripleStore: The store.

    Raises:
        TripleStoreUnavailableError: If the store cannot be reached, or does not answer in time.
        AuthenticationError: If the store answers 401.
        TripleStoreAccessError: If the store answers 403.
        InvalidDatasetError: If the dataset does not exist.
        TripleStoreResponseError: If the store answers with any other error status.
    """
    store = GraphDB(endpoint=endpoint, auth=auth)
    try:
        # The probe is the first request, so the provider logs in before it is sent.
        _probe(store)
    except BaseException:
        store.close()
        raise
    store.logger.info(
        f"Connected to repository '{endpoint.dataset}' at {endpoint.url}."
    )
    return store
