from __future__ import annotations

from typing import List, NoReturn, Union, Optional, Dict
from urllib.parse import quote
from kapps_triplestore_interface.kafka.kafka_manager import KafkaManager
import requests
import logging
import threading
import warnings
from requests import Response
from urllib3.exceptions import ProtocolError
from kapps_triplestore_interface import _deprecation
from kapps_triplestore_interface.auth import BasicAuth, GDBTokenAuth, _TripleStoreAuth
from kapps_triplestore_interface.store import TripleStoreEndpoint
from kapps_triplestore_interface.utils.graph_db_credentials import _GraphDBCredentials
from kapps_triplestore_interface.utils.iri import IRI
from kapps_triplestore_interface.utils.types import GraphNameLike, GraphName
from kapps_triplestore_interface.sparql_query import SPARQLQuery
from kapps_triplestore_interface.exceptions import (
    InvalidDatasetError,
    AuthenticationError,
    TripleStoreAccessError,
    TripleStoreResponseError,
    TripleStoreUnavailableError,
    TripleStoreNotSupportedError,
    ShaclValidationError,
)
from kapps_triplestore_interface.utils.utils import convert_multi_bindings_to_python_type

# The store states in the media type that its answer is a SHACL validation report. The RDF
# format follows after a `+`: GraphDB 10.8.1 answers a refused update with HTTP 500 and
# `application/shacl-validation-report+n-quads`. The body is not inspected: the error text
# of a malformed update quotes values from the update, and an update can name `sh:` terms.
SHACL_VALIDATION_REPORT_MEDIA_TYPE = "application/shacl-validation-report"


def _carries_validation_report(response: Response) -> bool:
    media_type = response.headers.get("Content-Type", "").split(";", 1)[0]
    return media_type.strip().lower().startswith(SHACL_VALIDATION_REPORT_MEDIA_TYPE)


# The error statuses that name an action of their own. Any other error status is the general
# `TripleStoreResponseError`.
_ERROR_FOR_STATUS: Dict[int, type[TripleStoreResponseError]] = {
    401: AuthenticationError,
    403: TripleStoreAccessError,
}


def _raise_error_answer(
    logger: logging.Logger, response: Response, failure: str
) -> NoReturn:
    """Log the store's error answer and raise it, typed by its action, with its status.

    The message is `failure`, then the status and the store's answer unchanged:
    `<failure> (<status>) - <answer>`.

    A validation report is a refusal, whatever the status. A refusal is an outcome the caller
    expects and catches, so the caller decides how loud it is: it is logged only at DEBUG, and
    the report travels in the error. Every other error answer is logged at ERROR, and its
    status selects its type.
    """
    status = response.status_code
    message = f"{failure} ({status}) - {response.text}"
    if _carries_validation_report(response):
        logger.debug(message)
        raise ShaclValidationError(message, report=response.text, status=status)
    logger.error(message)
    raise _ERROR_FOR_STATUS.get(status, TripleStoreResponseError)(message, status=status)


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


# The graph that a GraphDB repository with SHACL validation reads its shapes from: RDF4J's
# reserved shapes graph. A SPARQL query does not see the shapes in it.
_SHAPES_GRAPH = "http://rdf4j.org/schema/rdf4j#SHACLShapeGraph"


def _true_or_false(params: Dict, name: str) -> Optional[bool]:
    """The flag `name` of a configuration's `params`: `True`, `False`, or `None` when the
    params have no such flag, or its value is neither true nor false."""
    param = params.get(name)
    if not isinstance(param, dict):
        return None
    value = str(param.get("value")).strip().lower()
    return {"true": True, "false": False}.get(value)


def _shacl_validation_on(configuration: object) -> Optional[bool]:
    """Whether a repository validates with SHACL, as its configuration says, or `None`.

    `configuration` is GraphDB's answer to `GET /rest/repositories/<id>`. Its `params` hold
    `isShacl`, which is true when the repository was created with SHACL validation, and
    `validationEnabled`, which can turn the validation off.

    - `True`: `isShacl` is true, and `validationEnabled` is not false.
    - `False`: `isShacl` is false, or `validationEnabled` is false.
    - `None`: the configuration does not say: it has no `isShacl` with a value of true or false.

    Both flags are those of GraphDB 11.1's documentation of its REST API. Measured on GraphDB
    10.8.5, for repositories created from an RDF4J configuration file: `isShacl` is true when
    the file wraps the store in an `rdf4j:ShaclSail`, and false for a plain `graphdb:Sail`.
    GraphDB 10.8.1 answers true for the first as well.
    """
    if not isinstance(configuration, dict):
        return None
    params = configuration.get("params")
    if not isinstance(params, dict):
        return None
    shacl = _true_or_false(params, "isShacl")
    if shacl is None:
        return None
    return shacl and _true_or_false(params, "validationEnabled") is not False


def _probe(store: GraphDB) -> None:
    """Check that `store` answers, accepts the identity, and has the dataset: `ASK {}` on it.

    Raises:
        TripleStoreUnavailableError: If the store gives no answer.
        AuthenticationError: If the store answers 401, also after one new login.
        TripleStoreAccessError: If the store answers 403.
        InvalidDatasetError: If the store answers 404: the dataset does not exist.
        TripleStoreResponseError: If the store answers with any other error status.
    """
    response = store._make_request(
        "post",
        f"repositories/{store._repository}",
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
        data="ASK {}",
        retry_after_idle_close=True,
    )
    if response.status_code == 404:
        message = (
            f"The store at {store._endpoint.url} has no repository '{store._repository}'"
            f" ({response.status_code}) - {response.text}"
        )
        store.logger.error(message)
        raise InvalidDatasetError(message)
    if not response.ok:
        _raise_error_answer(
            store.logger,
            response,
            f"The store refused the probe of repository '{store._repository}'",
        )


class GraphDB:
    """
    The GraphDB adapter: a store of the contract `TripleStore`, on a GraphDB repository.

    Build it from a `TripleStoreEndpoint` and an auth provider, `GDBTokenAuth` or `BasicAuth`.
    `connect()` builds it so and checks it; code above the interface types it as
    `TripleStore`. It provides methods for querying and updating data, manages
    authentication, the dataset, a default named graph, and a Kafka connector manager.

    Args:
        endpoint (TripleStoreEndpoint): The store's URL and dataset.
        auth (BasicAuth | GDBTokenAuth): The auth provider of the identity.
        timeout (int): The timeout of a request, in seconds. Defaults to 60.
        named_graph (Optional[GraphNameLike]): The default named graph, or `None`.
        logger (Optional[logging.Logger]): The logger. Defaults to one named after the class.
    """

    def __init__(
        self,
        credentials: Optional[_GraphDBCredentials] = None,
        timeout: int = 60,
        use_gdb_token: Optional[bool] = None,
        named_graph: Optional[GraphNameLike] = None,
        logger: Optional[logging.Logger] = None,
        *,
        endpoint: Optional[TripleStoreEndpoint] = None,
        auth: Optional[BasicAuth | GDBTokenAuth] = None,
    ):
        """Build a client, from `credentials`, or from an `endpoint` and an `auth` provider.

        Built from an endpoint and a provider, the client sends no request: the provider logs in
        at the first request. `connect()` builds a client this way, then checks it with a login
        and a probe.

        `credentials` and `use_gdb_token` are deprecated; an endpoint and an auth provider
        replace them. Built from `credentials`, the client logs in, lists the datasets and
        checks that `credentials.repository` is one of them, as before. `use_gdb_token` chooses
        the provider for `credentials`: the GDB token when it is not given or true, Basic
        authentication when it is false. Each call that gives it emits one
        `DeprecationWarning`, which names the two providers.

        Raises:
            TypeError: If neither `credentials` nor both `endpoint` and `auth` are given, or
                if both are.
        """
        if logger is None:
            self.logger = logging.getLogger(self.__class__.__name__)
        else:
            self.logger = logger
        if use_gdb_token is not None:
            warnings.warn(
                "use_gdb_token is deprecated; pass an auth provider, which replaces it:"
                " GDBTokenAuth for use_gdb_token=True, BasicAuth for use_gdb_token=False.",
                DeprecationWarning,
                stacklevel=2,
            )
        if credentials is not None:
            if endpoint is not None or auth is not None:
                raise TypeError(
                    "GraphDB takes either credentials, or an endpoint and an auth provider,"
                    " not both."
                )
            endpoint = TripleStoreEndpoint(
                url=credentials.base_url, dataset=credentials.repository
            )
            if use_gdb_token is None or use_gdb_token:
                auth = GDBTokenAuth(credentials.username, credentials.password)
            else:
                auth = BasicAuth(credentials.username, credentials.password)
        elif endpoint is None or auth is None:
            raise TypeError(
                "GraphDB needs either credentials, or an endpoint and an auth provider."
            )
        self._credentials = credentials
        self._endpoint = endpoint
        self._auth_provider: _TripleStoreAuth = auth
        self._timeout = timeout
        # The `Authorization` header of the last request, `None` before the first one.
        self._auth: Optional[str] = None
        self._repositories: Optional[List[str]] = None
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

        if credentials is None:
            # No request: the provider logs in at the first one.
            self._repository = endpoint.dataset
            self._named_graph = IRI(named_graph) if named_graph is not None else None
        else:
            self._auth = auth._authorization(self)
            self._repositories = self.datasets_get(only_ids=True)
            self.dataset = credentials.repository
            self.named_graph = named_graph

        self.kafka_manager = KafkaManager(db=self)

        if credentials is not None:
            self.logger.info(
                f"Using GraphDB repository '{self._repository}' as user '{credentials.username}'."
            )

    @classmethod
    def from_env(
        cls,
        logger: Optional[logging.Logger] = None,
    ) -> GraphDB:
        """
        Construct a client from the variables `GRAPHDB_URL`, `GRAPHDB_USERNAME`,
        `GRAPHDB_PASSWORD` and `GRAPHDB_REPOSITORY`, with the GDB token.

        The client logs in, lists the datasets and checks that the dataset is one of them.

        Returns:
            GraphDB: The client.

        Raises:
            ValueError: If one of the variables is not set.
        """
        return cls(credentials=_GraphDBCredentials.from_env(), logger=logger)

    from kapps_triplestore_interface.queries.named_graph import (
        graphs_get,
        get_list_of_named_graphs,
    )
    from kapps_triplestore_interface.queries.rdf4j.graph_store import (
        graph_get,
        graph_add,
        graph_clear,
        fetch_statements,
        import_statements,
        clear_graph,
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
        """
        The dataset that the store's operations act on. GraphDB calls it a repository.

        Setting it selects another dataset of the store, after a check that the store has it.

        Raises:
            InvalidDatasetError: When it is set to a dataset that the store does not have.
        """
        return self._repository

    @dataset.setter
    def dataset(
        self,
        value: str,
    ):
        # A client built from an endpoint has not listed the datasets yet.
        if self._repositories is None:
            self._repositories = self.datasets_get(only_ids=True)
        self._repository = self._validate_repository(value)

    @property
    @_deprecation.renamed("dataset")
    def repository(self) -> str:
        """The deprecated name of `dataset`."""
        return self.dataset

    @repository.setter
    @_deprecation.renamed("dataset")
    def repository(
        self,
        value: str,
    ):
        self.dataset = value

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

    def datasets_get(
        self,
        only_ids: Optional[bool] = False,
    ) -> Union[List[str], List[dict]]:
        """
        List the datasets of the store: GraphDB's repositories.

        Args:
            only_ids (Optional[bool]): When True, return only the dataset ids. When False,
                return GraphDB's full repository descriptors. Defaults to False.

        Returns:
            Union[List[str], List[dict]]: A list of ids if `only_ids=True`, a list of
            repository descriptors otherwise. An error answer raises instead.

        Raises:
            AuthenticationError: If the store answers 401.
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status. It is
                logged at ERROR.
            TripleStoreUnavailableError: If the store gives no answer. When the store closed the
                connection without an answer, the read is sent once more, on a fresh
                connection, and raises only if that fails as well.
        """
        response = self._make_request(
            "get", "rest/repositories", retry_after_idle_close=True
        )

        if response.status_code == 200:
            repositories = response.json()
            if only_ids:
                return [repo["id"] for repo in repositories]
            return repositories

        _raise_error_answer(self.logger, response, "Failed to list repositories")

    @_deprecation.renamed("datasets_get")
    def get_list_of_repositories(
        self,
        only_ids: Optional[bool] = False,
    ) -> Union[List[str], List[dict]]:
        """The deprecated name of `datasets_get`."""
        return self.datasets_get(only_ids=only_ids)

    def _validate_repository(
        self,
        repository: str,
    ) -> str:
        """
        Validate that the repository exists on the server.

        Args:
            repository (str): The repository identifier to validate.

        Returns:
            str: The validated repository identifier.

        Raises:
            InvalidDatasetError: If the repository is not available.
        """
        if self._repositories == []:
            raise InvalidDatasetError(
                f"The server at {self._endpoint.url} has no repositories."
                " It may not have created them yet; wait and try again."
            )
        if repository not in self._repositories:
            raise InvalidDatasetError(
                "Invalid repository name. Allowed values are:"
                f" {', '.join(list(self._repositories))}."
            )
        return repository

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
        Perform an authenticated HTTP request to the GraphDB REST API.

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
                no answer, the request is sent once more on a fresh connection. Only a read
                sets it. Any other failure is raised, and a second failure is raised as well.
                Defaults to False: a write is never sent again, because the store may have
                applied it, and a second send could apply it twice.
            authenticate (bool): Whether the request carries the provider's header. Only the
                login itself sets it to False.
            **kwargs: Additional arguments forwarded to `requests`.

        Returns:
            Response: The `requests.Response` object, also for an error status: the caller
            reads the status.

        Raises:
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
            return self._session.request(
                method,
                url,
                headers=sent_headers,
                timeout=timeout,
                **kwargs,
            )

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
                    f"The store closed the connection without an answer ({error}). Sending the read again on a fresh connection."
                )
                self._session.close()
                return send(authorization)

        try:
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
        except _NO_ANSWER as error:
            raise TripleStoreUnavailableError(
                f"No answer from the store to {method.upper()} {url}: {error}"
            ) from error

    @property
    def _session(self) -> requests.Session:
        """This thread's persistent session, created on first use."""
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            self._thread_local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    def close(self) -> None:
        """Release the HTTP connection pools held for every thread that used this client."""
        with self._sessions_lock:
            sessions, self._sessions = self._sessions, []
        for session in sessions:
            session.close()

    def _get_authentication_token(
        self,
        username: str,
        password: str,
    ) -> str:
        """
        Obtain a GraphDB authentication token.

        Args:
            username (str): The GraphDB username.
            password (str): The GraphDB password.

        Returns:
            str: The `Authorization` header value (e.g., `Bearer ...`).

        Raises:
            AuthenticationError: If the store does not accept the credentials (401).
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status.
            TripleStoreUnavailableError: If the store gives no answer.
        """
        payload = {
            "username": username,
            "password": password,
        }
        response = self._make_request(
            "post", "rest/login", authenticate=False, json=payload
        )
        if response.status_code == 200:
            return response.headers.get("Authorization")

        _raise_error_answer(self.logger, response, "Failed to obtain a GDB token")

    def query(
        self,
        query: Union[SPARQLQuery, str],
        update: Optional[bool] = False,
        convert_bindings: Optional[bool] = False,
    ) -> Union[Dict, bool]:
        """
        Execute a SPARQL query or update against the repository.

        Args:
            query (Union[SPARQLQuery, str]): The SPARQL query/update string to execute.
            update (Optional[bool]): If True, perform an update; otherwise perform a read query.
                Defaults to False.
            convert_bindings (Optional[bool]): Whether to convert query result bindings to Python types.
                Defaults to True.

        Returns:
            Union[Dict, bool]: If `update` is False, the parsed JSON result dict.
            If `update` is True, `True`. A failure raises instead.

        Raises:
            TypeError: If the `query` parameter is neither a `SPARQLQuery` nor a string.
            InvalidQueryError: If the SPARQL query is malformed.
            ShaclValidationError: If the store refused the update because the data would
                violate a SHACL shape. Its `report` is the store's validation report. The
                refusal is logged only at DEBUG; the caller decides how loud it is.
            AuthenticationError: If the store answers 401.
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status. Its
                `status` is that status. It is logged at ERROR, as are the two above.
            TripleStoreUnavailableError: If the request gets no answer. When the store closed
                the connection without an answer, a read (`update=False`) is sent once more, on
                a fresh connection, and raises only if that fails as well. An update is never
                sent again.
        """
        if isinstance(query, SPARQLQuery):
            query = query.to_string()
        elif not isinstance(query, str):
            raise TypeError("Query must be a SPARQLQuery or a string.")

        endpoint = f"repositories/{self._repository}"
        headers = {
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        }

        if update:
            endpoint += "/statements"
            headers["Content-Type"] = "application/sparql-update"
        response = self._make_request(
            "post",
            endpoint,
            headers=headers,
            data=query,
            retry_after_idle_close=not update,
        )

        if not response.ok:
            _raise_error_answer(self.logger, response, "Error while querying GraphDB")

        if update:
            self.logger.debug(
                'Query\n"""\n%s\n"""\nReturned\nUpdate successful (200)', query
            )
            return True

        response = response.json()
        # The answer can be large; format it only when the line is written.
        self.logger.debug('Query\n"""\n%s\n"""\nReturned\n%s', query, response)

        if (
            convert_bindings
            and "results" in response
            and "bindings" in response["results"]
        ):
            bindings = response["results"]["bindings"]
            converted_bindings = convert_multi_bindings_to_python_type(bindings)
            response["results"]["bindings"] = converted_bindings

        return response

    # -- the store registries: the dataset's prefixes and its SHACL shapes -------------------

    def _namespace_address(self, prefix: Optional[str] = None) -> str:
        """The address of the dataset's prefixes, or of `prefix` alone.

        The empty prefix's address ends with the slash, `namespaces/`. GraphDB takes it for the
        empty prefix alone (10.8.1 and 10.8.5); `namespaces` without the slash is the address
        of every prefix, and a DELETE there deletes them all. The prefix is quoted, so that it
        stays one segment of the path.
        """
        address = f"repositories/{self._repository}/namespaces"
        if prefix is None:
            return address
        return f"{address}/{quote(prefix, safe='')}"

    def prefixes_get(self) -> Dict[str, str]:
        """Each prefix of the dataset, with the namespace IRI that it stands for.

        Reads the dataset's namespaces, RDF4J's prefix registry. The empty prefix, if the
        dataset has one, is the key `""`.

        Returns:
            Dict[str, str]: The namespace IRI of each prefix.

        Raises:
            AuthenticationError: If the store answers 401.
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status. The
                message names the repository.
            TripleStoreUnavailableError: If the request gets no answer. When the store closed
                the connection without an answer, the read is sent once more, on a fresh
                connection, and raises only if that fails as well.
        """
        response = self._make_request(
            "get",
            self._namespace_address(),
            headers={"Accept": "application/sparql-results+json"},
            retry_after_idle_close=True,
        )
        if not response.ok:
            _raise_error_answer(
                self.logger,
                response,
                f"Failed to read the prefixes of repository '{self._repository}'",
            )
        return {
            row["prefix"]["value"]: row["namespace"]["value"]
            for row in response.json()["results"]["bindings"]
        }

    def prefix_set(self, prefix: str, iri: str) -> None:
        """Let `prefix` stand for the namespace `iri` in the dataset.

        A prefix that the dataset has already stands for `iri` afterwards. `""` is the empty
        prefix. The store checks the prefix and the IRI.

        Raises:
            AuthenticationError: If the store answers 401.
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status, for
                example to a prefix that it does not accept. The message names the repository.
            TripleStoreUnavailableError: If the request gets no answer. The write is not sent
                again.
        """
        response = self._make_request(
            "put",
            self._namespace_address(prefix),
            headers={"Content-Type": "text/plain"},
            data=iri,
        )
        if not response.ok:
            _raise_error_answer(
                self.logger,
                response,
                f"Failed to set the prefix '{prefix}' in repository '{self._repository}'",
            )

    def prefix_delete(self, prefix: str) -> None:
        """Remove `prefix` from the dataset. Every other prefix stays. `""` is the empty prefix.

        Raises:
            AuthenticationError: If the store answers 401.
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status. The
                message names the repository.
            TripleStoreUnavailableError: If the request gets no answer. The write is not sent
                again.
        """
        response = self._make_request("delete", self._namespace_address(prefix))
        if not response.ok:
            _raise_error_answer(
                self.logger,
                response,
                f"Failed to delete the prefix '{prefix}' in repository '{self._repository}'",
            )

    def _repository_configuration(self) -> object:
        """The repository's configuration, as GraphDB's REST API answers it.

        Raises:
            The error of `_raise_error_answer` for an error answer, and
            `TripleStoreUnavailableError` if the request gets no answer.
        """
        response = self._make_request(
            "get",
            f"rest/repositories/{self._repository}",
            headers={"Accept": "application/json"},
            retry_after_idle_close=True,
        )
        if not response.ok:
            _raise_error_answer(
                self.logger,
                response,
                f"Failed to read the configuration of repository '{self._repository}'",
            )
        return response.json()

    def shapes_set(self, data: str, content_type: str) -> None:
        """Replace the SHACL shapes that the store validates the dataset against with `data`.

        `content_type` is the media type of `data`, for example `text/turtle`; the store parses
        `data`. An empty document, or one of white space only, removes every shape.

        GraphDB turns SHACL validation on only when a repository is created. On a repository
        without it, the shapes would be stored as plain data that validates nothing. So the
        adapter first reads the repository's configuration, and raises
        `TripleStoreNotSupportedError` when it does not say that SHACL validation is on.

        Then it replaces RDF4J's shapes graph with `data` in one request, a PUT on the graph
        store, which the store commits whole or not at all. A store with SHACL validation checks
        the data of the dataset against the new shapes when it commits them, and refuses the
        replacement when the data violates them; the old shapes then stay, and the store
        validates against them as before (measured on GraphDB 10.8.5). An empty document is
        one DELETE of the shapes graph.

        Raises:
            TripleStoreNotSupportedError: If the configuration does not say that the dataset has
                SHACL validation. Nothing is written.
            ShaclValidationError: If the store refused the replacement, because the data of the
                dataset violates the new shapes. Its `report` is the store's validation report.
                The old shapes stay.
            AuthenticationError: If the store answers 401.
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status, for
                example to a document that it cannot parse. The message names the repository.
            TripleStoreUnavailableError: If a request gets no answer. A write is not sent again.
        """
        validation = _shacl_validation_on(self._repository_configuration())
        if validation is not True:
            reason = (
                "does not say whether SHACL validation is on"
                if validation is None
                else "says that SHACL validation is off"
            )
            raise TripleStoreNotSupportedError(
                f"Cannot set the SHACL shapes of repository '{self._repository}': its"
                f" configuration {reason}. A repository gets SHACL validation only when it is"
                " created."
            )
        graph = {"graph": _SHAPES_GRAPH}
        address = f"repositories/{self._repository}/rdf-graphs/service"
        if data.strip():
            response = self._make_request(
                "put",
                address,
                params=graph,
                headers={"Content-Type": content_type},
                data=data,
            )
        else:
            response = self._make_request("delete", address, params=graph)
        if not response.ok:
            _raise_error_answer(
                self.logger,
                response,
                f"Failed to set the SHACL shapes of repository '{self._repository}'",
            )
