"""The client that the adapters share: `RDF4JClient`, the transport and the data operations of a
store that speaks the RDF4J protocol."""

from __future__ import annotations

import logging
import re
import threading
from typing import Dict, NoReturn, Optional, Union

import requests
from rdflib import Graph
from requests import Response
from urllib3.exceptions import ProtocolError

from kapps_triplestore_interface.auth import _TripleStoreAuth
from kapps_triplestore_interface.exceptions import (
    AuthenticationError,
    InvalidDatasetError,
    ShaclValidationError,
    TripleStoreAccessError,
    TripleStoreResponseError,
    TripleStoreUnavailableError,
)
from kapps_triplestore_interface.queries import checked_write as _checked_write
from kapps_triplestore_interface.sparql_query import SPARQLQuery
from kapps_triplestore_interface.store import TripleStoreEndpoint
from kapps_triplestore_interface.utils.iri import IRI
from kapps_triplestore_interface.utils.types import GraphName, GraphNameLike
from kapps_triplestore_interface.utils.utils import (
    convert_multi_bindings_to_python_type,
)

# The store states in the media type that its answer is a SHACL validation report. The RDF
# format follows after a `+`: GraphDB 10.8.1 answers a refused update with HTTP 500 and
# `application/shacl-validation-report+n-quads`. The body is not inspected: the error text
# of a malformed update quotes values from the update, and an update can name `sh:` terms.
SHACL_VALIDATION_REPORT_MEDIA_TYPE = "application/shacl-validation-report"


def _media_type_of(response: Response) -> str:
    """The media type of an answer, in lower case, without its parameters."""
    return response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()


def _carries_validation_report(response: Response) -> bool:
    return _media_type_of(response).startswith(SHACL_VALIDATION_REPORT_MEDIA_TYPE)


# The RDF formats of a CONSTRUCT or DESCRIBE answer that `query()` reads into a `Graph`, by
# media type. A read offers N-Triples; the others are read when a store picks one anyway. An
# answer of any other media type is read as a JSON result table, as before.
_RDF_MEDIA_TYPES = frozenset(
    {
        "application/n-triples",
        "text/turtle",
        "application/rdf+xml",
        "application/ld+json",
    }
)


def _rdf_format_of(response: Response) -> Optional[str]:
    """The media type of an RDF answer, which names rdflib's parser, or `None`."""
    media_type = _media_type_of(response)
    return media_type if media_type in _RDF_MEDIA_TYPES else None


# The DEBUG line of a read: the query and what it returned.
_QUERY_LOG = 'Query\n"""\n%s\n"""\nReturned\n%s'


class _LazyText:  # pylint: disable=too-few-public-methods
    """The body of an answer, decoded as UTF-8 only when a log line formats it."""

    def __init__(self, response: Response):
        self._response = response

    def __str__(self) -> str:
        return self._response.content.decode("utf-8", errors="replace")


# The error statuses that name an action of their own. Any other error status is the general
# `TripleStoreResponseError`.
_ERROR_FOR_STATUS: Dict[int, type[TripleStoreResponseError]] = {
    401: AuthenticationError,
    403: TripleStoreAccessError,
}


def _raise_error_answer(
    logger: logging.Logger,
    response: Response,
    failure: str,
    message: Optional[str] = None,
) -> NoReturn:
    """Log the store's error answer and raise it, typed by its action, with its status.

    The message is `message`, else `failure`, then the status and the store's answer
    unchanged: `<failure> (<status>) - <answer>`.

    A validation report is a refusal, whatever the status. A refusal is an outcome the caller
    expects and catches, so the caller decides how loud it is: it is logged only at DEBUG, and
    the report travels in the error. Every other error answer is logged at ERROR, and its
    status selects its type.
    """
    status = response.status_code
    if message is None:
        message = f"{failure} ({status}) - {response.text}"
    if _carries_validation_report(response):
        logger.debug(message)
        raise ShaclValidationError(message, report=response.text, status=status)
    logger.error(message)
    raise _ERROR_FOR_STATUS.get(status, TripleStoreResponseError)(
        message, status=status
    )


# The failures of a request that got no answer: the store cannot be reached, it did not answer
# in time, or the connection dropped, also while the answer arrived. `requests.ConnectTimeout`
# is both a `ConnectionError` and a `Timeout`, and an SSL failure is a `ConnectionError`. Each
# raises `TripleStoreUnavailableError`, chained to it. Any other error of the HTTP client is a
# request that it could not build, such as a URL without a scheme, and is raised unchanged.
_NO_ANSWER = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _connection_aborted(error: requests.ConnectionError) -> bool:
    """Whether the store closed the connection after the request went out on it.

    requests wraps urllib3's `ProtocolError('Connection aborted.', ...)`, for example with
    `RemoteDisconnected` or `ConnectionResetError`. A store that cannot be reached at all
    gives a different cause, which is not retried.
    """
    return bool(error.args) and isinstance(error.args[0], ProtocolError)


def _raise_missing_dataset(store: RDF4JClient, response: Response) -> NoReturn:
    """Log and raise `InvalidDatasetError` for an answer that says the dataset does not exist.

    The message names the store, the dataset, the status and the store's answer unchanged.
    """
    message = (
        f"The store at {store._endpoint.url} has no repository '{store._repository}'"
        f" ({response.status_code}) - {response.text}"
    )
    store.logger.error(message)
    raise InvalidDatasetError(message)


def _names_unknown_dataset(response: Response, dataset: str) -> bool:
    """Whether the store answered that it does not know `dataset`.

    RDF4J's server, and GraphDB with it, answers a request to a repository that it does not
    have with 404 and `Unknown repository: <id>`. The status alone does not say it: the graph
    store answers 404 for a named graph that it does not have, too. Kadi states its own errors
    in JSON, which does not start so.
    """
    if response.status_code != 404:
        return False
    return (
        re.match(rf"\s*Unknown repository: {re.escape(dataset)}(?!\S)", response.text)
        is not None
    )


class RDF4JClient:
    """
    The client of a store that speaks the RDF4J protocol, with the data operations of the store.

    It sends SPARQL queries, SPARQL updates and Graph Store requests to one dataset below an
    endpoint, authenticated by an auth provider, and holds the dataset and a default named
    graph.

    Args:
        endpoint (TripleStoreEndpoint): The store's URL and dataset.
        auth: The auth provider of the identity.
        timeout (int): The timeout of a request, in seconds. Defaults to 60.
        named_graph (Optional[GraphNameLike]): The default named graph, or `None`.
        logger (Optional[logging.Logger]): The logger. Defaults to one named after the class.
        store_name (str): What the client talks to, as its error messages name it. Defaults
            to `the store`.
    """

    # The `Accept` of a read: the JSON result format of a SELECT or an ASK, and N-Triples for
    # a CONSTRUCT or DESCRIBE. The store picks the one that fits the query form, so the client
    # reads nothing from the query text. An adapter whose store is not known to negotiate
    # overrides it.
    _READ_ACCEPT = "application/sparql-results+json, application/n-triples;q=0.9"

    def __init__(
        self,
        endpoint: TripleStoreEndpoint,
        auth: _TripleStoreAuth,
        timeout: int = 60,
        named_graph: Optional[GraphNameLike] = None,
        logger: Optional[logging.Logger] = None,
        store_name: str = "the store",
    ):
        """Build a client. It sends no request: the provider logs in at the first one."""
        if logger is None:
            self.logger = logging.getLogger(self.__class__.__name__)
        else:
            self.logger = logger
        self._endpoint = endpoint
        self._store_name = store_name
        self._auth_provider: _TripleStoreAuth = auth
        self._timeout = timeout
        # The `Authorization` header of the last request, `None` before the first one.
        self._auth: Optional[str] = None
        self._blank_ids = set()

        # A persistent session per thread, so the connection pool survives across calls.
        # The module-level `requests.get`/`requests.post` helpers build a throwaway session
        # per call, which means a new TCP connect and a full TLS handshake for every SPARQL
        # query — against a remote HTTPS endpoint that dominates the cost of a query, and a
        # client typically issues many.
        #
        # Per thread rather than one shared session, because a `requests.Session` is not
        # thread-safe: its cookie jar is mutated by every response. One client is commonly
        # driven from several threads at once — a web framework serving requests while the
        # embedding code queries — and urllib3's pools are thread-safe but the session
        # around them is not. Each thread pays one handshake and then reuses its own pool.
        self._thread_local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock = threading.Lock()
        # Counts the calls of `close()`. A thread's session belongs to the count it was opened
        # at; after a `close()` the thread opens a new one, which the next `close()` releases.
        # The closing thread cannot drop the other threads' sessions from their thread-locals.
        self._sessions_generation = 0

        # The receipts of this client's checked writes whose `ASK` has found them, still to
        # remove. The next checked write of any thread carries their removal, and `close()`
        # removes the rest (`queries/checked_write.py`).
        self._receipts_to_remove = _checked_write.ReceiptsToRemove()

        self._repository = endpoint.dataset
        self._named_graph = IRI(named_graph) if named_graph is not None else None

    from kapps_triplestore_interface.queries.named_graph import graphs_get
    from kapps_triplestore_interface.queries.rdf4j.graph_store import (
        graph_get,
        graph_add,
        graph_clear,
    )

    from kapps_triplestore_interface.queries.triple_single import (
        triple_exists,
        triple_add,
        triple_delete,
        triple_update,
    )
    from kapps_triplestore_interface.queries.triple_multi import (
        triples_get,
        any_triple_exists,
        all_triple_exists,
        triples_add,
        triples_delete,
        triples_update,
    )
    from kapps_triplestore_interface.queries.ontology_helpers import (
        iri_exists,
        new_iri,
        new_blank_id,
        is_subclass,
        owl_is_named_individual,
        owl_get_classes_of_individual,
    )

    @property
    def dataset(self) -> str:
        """The dataset that the store's operations act on. GraphDB calls it a repository."""
        return self._repository

    @property
    def named_graph(self) -> Optional[GraphName]:
        """
        The currently selected default named graph.

        Returns:
            Optional[IRI]: The default named graph as an `IRI`, or `None` if unset.
        """
        return self._named_graph

    @named_graph.setter
    def named_graph(
        self,
        value: Optional[GraphNameLike],
    ):
        if value is None:
            self._named_graph = None
            return

        value = IRI(value)

        if value not in self.graphs_get():
            self.logger.warning(
                f"Passed named graph {value} does not exist in the repository."
            )
        self._named_graph = value

    @property
    def named_graph_str(self) -> Optional[str]:
        """
        The selected default named graph as a string.

        Returns:
            Optional[str]: The IRI string of the default named graph, or `None`.
        """
        if self._named_graph is None:
            return None
        return str(self._named_graph)

    def _make_request(
        self,
        method: str,
        endpoint: str,
        timeout: Optional[int] = None,
        retry_after_idle_close: bool = False,
        authenticate: bool = True,
        **kwargs,
    ) -> Response:
        """
        Perform an authenticated HTTP request to the store's REST API.

        The auth provider gives the request its `Authorization` header, and logs in first when
        it must. When the store answers 401, the provider renews once, and the request is sent
        once more with the new header; its answer is returned, also a second 401. This is safe
        for a write too: a store that answers 401 has not applied the write. A provider that has
        nothing to renew, such as Basic authentication, returns the first 401.

        Args:
            method (str): The HTTP method (e.g., "get", "post").
            endpoint (str): The REST endpoint path relative to `base_url`.
            timeout (Optional[int]): Request timeout in seconds; defaults to the client setting.
            retry_after_idle_close (bool): Marks the request as safe to send again. When the
                store closed the pooled connection while it sat idle, so that the request got
                no answer, the request is sent once more on a fresh connection. Only a read,
                and the login, set it. Any other failure is raised, and a second failure is
                raised as well.
                Defaults to False: a write is never sent again, because the store may have
                applied it, and a second send could apply it twice.
            authenticate (bool): Whether the request carries the provider's header. Only the
                login itself sets it to False.
            **kwargs: Additional arguments forwarded to `requests`.

        Returns:
            Response: The `requests.Response` object, also for an error status: the caller
            reads the status. The one error answer read here is an unknown dataset, see
            Raises.

        Raises:
            InvalidDatasetError: If the store answers that it does not know the dataset: 404
                and `Unknown repository: <dataset>`, as for a dataset deleted after
                `connect()`. Any other 404 is returned, for the caller to read.
            TripleStoreUnavailableError: If the request got no answer: the store cannot be
                reached, it did not answer in time, or the connection dropped. It is chained to
                the error of the HTTP client.
        """
        timeout = timeout if timeout is not None else self._timeout

        headers = kwargs.pop("headers", {})

        url = f"{self._endpoint.url}/{endpoint}"

        def send(authorization: Optional[str]) -> Response:
            sent_headers = dict(headers)
            if authorization is not None:
                sent_headers["Authorization"] = authorization
            session = self._session
            try:
                return session.request(
                    method,
                    url,
                    headers=sent_headers,
                    timeout=timeout,
                    **kwargs,
                )
            finally:
                # A `close()` of another thread while the request was on its way has closed
                # the session, and the request opened a connection pool in it again. The
                # thread opens a new session at its next request, so this one is closed now.
                if self._thread_local.generation != self._sessions_generation:
                    session.close()

        def send_once_more_after_idle_close(authorization: Optional[str]) -> Response:
            try:
                return send(authorization)
            except requests.ConnectionError as error:
                # The store closes a keep-alive connection that has been idle for a while (a
                # remote GraphDB measured: after 5 s). A request that leaves on it at that moment
                # gets no answer. A read is sent again once, on a fresh connection. A write is
                # never sent again, because the store may have applied it, and a second one could
                # apply it twice.
                if not retry_after_idle_close or not _connection_aborted(error):
                    raise
                self.logger.info(
                    f"The store closed the connection without an answer ({error}). Sending the request again on a fresh connection."
                )
                self._session.close()
                return send(authorization)

        def send_authenticated() -> Response:
            if not authenticate:
                return send_once_more_after_idle_close(None)
            authorization = self._auth_provider._authorization(self)
            self._auth = authorization
            response = send_once_more_after_idle_close(authorization)
            if response.status_code != 401:
                return response
            renewed = self._auth_provider._renew(self, authorization)
            if renewed is None:
                return response
            self.logger.info(
                f"The store answered 401 to {method.upper()} {url}. Logged in again; sending the request once more."
            )
            self._auth = renewed
            return send_once_more_after_idle_close(renewed)

        try:
            response = send_authenticated()
        except _NO_ANSWER as error:
            raise TripleStoreUnavailableError(
                f"No answer from the store to {method.upper()} {url}: {error}"
            ) from error
        if _names_unknown_dataset(response, self._repository):
            _raise_missing_dataset(self, response)
        return response

    @property
    def _session(self) -> requests.Session:
        """This thread's persistent session, created on first use, and again after `close()`."""
        local = self._thread_local
        session = getattr(local, "session", None)
        if session is not None and local.generation == self._sessions_generation:
            return session
        session = requests.Session()
        with self._sessions_lock:
            self._sessions.append(session)
            local.session = session
            local.generation = self._sessions_generation
        return session

    def close(self) -> None:
        """Remove the receipts still to remove, then release the HTTP connection pools.

        The receipts of the client's checked writes go in one update request, before the
        sessions close; no request goes when there is none. A failure of that request is
        logged as a warning and not raised: each receipt carries its time, and a later checked
        write removes it by its age. The sessions close all the same.

        The client stays usable: a request after `close()` opens a new session in its thread,
        and the next `close()` releases it.
        """
        try:
            _checked_write.remove_receipts(self)
        finally:
            self._close_sessions()

    def _close_sessions(self) -> None:
        """Release the HTTP connection pools held for every thread that used this client."""
        with self._sessions_lock:
            sessions, self._sessions = self._sessions, []
            self._sessions_generation += 1
        for session in sessions:
            session.close()

    def _error_message(  # pylint: disable=unused-argument
        self, response: Response
    ) -> Optional[str]:
        """The message of an error answer, or `None` for the one of `_raise_error_answer`.

        An adapter whose store states the reason of an error in its answer overrides it.
        """
        return None

    def _raise_error(self, response: Response, failure: str) -> NoReturn:
        """Log the error answer and raise it, see `_raise_error_answer`."""
        _raise_error_answer(
            self.logger, response, failure, self._error_message(response)
        )

    def _query_failure(self, update: bool) -> str:  # pylint: disable=unused-argument
        """The start of the message of a query or an update that the store refused."""
        return f"Error while querying {self._store_name}"

    def _graph_of(self, query: str, response: Response, rdf_format: str) -> Graph:
        """The triples of an RDF answer, parsed from its bytes.

        The bytes, not the text: an RDF format is UTF-8 unless its media type says otherwise,
        and requests guesses ISO-8859-1 for a `text/*` answer without a charset.

        Raises:
            TripleStoreResponseError: If the answer cannot be read in its format. Its status
                is the answer's.
        """
        graph = Graph()
        try:
            graph.parse(data=response.content, format=rdf_format)
        except Exception as error:  # pylint: disable=broad-exception-caught
            message = (
                f"{self._query_failure(False)}: the answer is not readable as "
                f"{rdf_format} ({error})"
            )
            self.logger.error(message)
            raise TripleStoreResponseError(
                message, status=response.status_code
            ) from error
        # The answer can be large; format it only when the line is written.
        self.logger.debug(_QUERY_LOG, query, _LazyText(response))
        return graph

    def query(
        self,
        query: Union[SPARQLQuery, str],
        update: Optional[bool] = False,
        convert_bindings: Optional[bool] = False,
    ) -> Union[Dict, bool, Graph]:
        """
        Execute a SPARQL query or update against the repository.

        What it returns depends on the query form:

        - SELECT: the JSON result dict, `{"head": ..., "results": {"bindings": [...]}}`.
        - ASK: the JSON result dict with the answer, `{"head": {}, "boolean": ...}`.
        - CONSTRUCT and DESCRIBE: an rdflib `Graph` of the resulting triples. Blank nodes
          are rdflib blank nodes. A read offers the store the JSON result format and
          N-Triples, and the store answers in the one that fits the form, so the client
          reads nothing from the query text, also after a prologue. To page a large result,
          write LIMIT and OFFSET (with ORDER BY) into the query.
        - An update (`update=True`): `True`.

        What parses on the client depends on who built the query:

        - The interface, for its own operations (`triples_get`, `triples_add`,
          `iri_exists` and the like): sent as text, not parsed. It renders every term
          itself, so a parse could find only a defect in its fixed template text.
        - A caller, as a `SPARQLQuery`: parsed first, as before. A malformed query raises
          `InvalidQueryError`.
        - A caller, as a `str`: sent as it is, without a parse, as before.

        Args:
            query (Union[SPARQLQuery, str]): The SPARQL query/update string to execute.
            update (Optional[bool]): If True, perform an update; otherwise perform a read query.
                Defaults to False.
            convert_bindings (Optional[bool]): Whether to convert query result bindings to Python types.
                Defaults to False. Ignored for a CONSTRUCT or DESCRIBE, which has no bindings.

        Returns:
            Union[Dict, bool, Graph]: If `update` is False, the parsed JSON result dict of a
            SELECT or an ASK, or the `Graph` of a CONSTRUCT or a DESCRIBE.
            If `update` is True, `True`. A failure raises instead.

        Raises:
            TypeError: If the `query` parameter is neither a `SPARQLQuery` nor a string.
            InvalidQueryError: If the SPARQL query is malformed.
            InvalidDatasetError: If the store answers that it does not know the dataset, as
                for a dataset deleted after `connect()`. The message names the dataset and
                the store's answer.
            ShaclValidationError: If the store refused the update because the data would
                violate a SHACL shape. Its `report` is the store's validation report. The
                refusal is logged only at DEBUG; the caller decides how loud it is.
            AuthenticationError: If the store answers 401.
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status. Its
                `status` is that status. It is logged at ERROR, as are the two above. It is
                also raised, with the answer's status, when the RDF answer to a CONSTRUCT or
                DESCRIBE cannot be read in its format.
            TripleStoreUnavailableError: If the request gets no answer. When the store closed
                the connection without an answer, a read (`update=False`) is sent once more, on
                a fresh connection, and raises only if that fails as well. An update is never
                sent again.
        """
        return self._query(query, update=update, convert_bindings=convert_bindings)

    def _query(
        self,
        query: Union[SPARQLQuery, str],
        update: Optional[bool] = False,
        convert_bindings: Optional[bool] = False,
        infer: Optional[bool] = None,
    ) -> Union[Dict, bool, Graph]:
        """`query`, with the RDF4J request parameter `infer` when `infer` is not `None`.

        A prototype for a measurement, not part of the store contract: `infer=False` asks the
        store for the explicit statements only, without a vendor graph in the query text.
        """
        if isinstance(query, SPARQLQuery):
            query = query.to_string()
        elif not isinstance(query, str):
            raise TypeError("Query must be a SPARQLQuery or a string.")

        request_parameters = {}
        if infer is not None:
            request_parameters["params"] = {"infer": "true" if infer else "false"}

        endpoint = f"repositories/{self._repository}"
        headers = {
            "Content-Type": "application/sparql-query",
            "Accept": self._READ_ACCEPT,
        }

        if update:
            endpoint += "/statements"
            headers["Content-Type"] = "application/sparql-update"
            headers["Accept"] = "application/sparql-results+json"
        response = self._make_request(
            "post",
            endpoint,
            headers=headers,
            data=query,
            retry_after_idle_close=not update,
            **request_parameters,
        )

        if not response.ok:
            self._raise_error(response, self._query_failure(update))

        if update:
            self.logger.debug(
                'Query\n"""\n%s\n"""\nReturned\nUpdate successful (200)', query
            )
            return True

        rdf_format = _rdf_format_of(response)
        if rdf_format is not None:
            return self._graph_of(query, response, rdf_format)

        response = response.json()
        # The answer can be large; format it only when the line is written.
        self.logger.debug(_QUERY_LOG, query, response)

        if (
            convert_bindings
            and "results" in response
            and "bindings" in response["results"]
        ):
            bindings = response["results"]["bindings"]
            converted_bindings = convert_multi_bindings_to_python_type(bindings)
            response["results"]["bindings"] = converted_bindings

        return response
