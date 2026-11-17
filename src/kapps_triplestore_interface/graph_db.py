from __future__ import annotations

from typing import List, Union, Optional, Dict
from urllib.parse import quote
import logging
import warnings
from rdflib import Graph
from kapps_triplestore_interface import _deprecation
from kapps_triplestore_interface.auth import BasicAuth, GDBTokenAuth
from kapps_triplestore_interface.store import TripleStoreEndpoint
from kapps_triplestore_interface.utils.graph_db_credentials import _GraphDBCredentials
from kapps_triplestore_interface.utils.types import GraphNameLike
from kapps_triplestore_interface.exceptions import (
    InvalidDatasetError,
    TripleStoreNotSupportedError,
)

# The media type stays importable from here, as before the client was shared.
from kapps_triplestore_interface.rdf4j_client import (  # pylint: disable=unused-import
    SHACL_VALIDATION_REPORT_MEDIA_TYPE,
    RDF4JClient,
    _raise_error_answer,
    _raise_missing_dataset,
)


# The graph that a GraphDB repository with SHACL validation reads its shapes from: RDF4J's
# reserved shapes graph. A SPARQL query does not see the shapes in it.
_SHAPES_GRAPH = "http://rdf4j.org/schema/rdf4j#SHACLShapeGraph"
# The query parameters that name the shapes graph on the graph store.
_SHAPES_GRAPH_PARAMS = {"graph": _SHAPES_GRAPH}


def _params_of(configuration: object) -> Optional[Dict]:
    """The `params` of a repository configuration, or `None` when it has none that is an
    object. `configuration` is GraphDB's answer to `GET /rest/repositories/<id>`."""
    if not isinstance(configuration, dict):
        return None
    params = configuration.get("params")
    return params if isinstance(params, dict) else None


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
    params = _params_of(configuration)
    if params is None:
        return None
    shacl = _true_or_false(params, "isShacl")
    if shacl is None:
        return None
    return shacl and _true_or_false(params, "validationEnabled") is not False


def _ruleset_of(configuration: object) -> Optional[str]:
    """The reasoning ruleset that a repository runs, as its configuration names it, or `None`.

    `configuration` is GraphDB's answer to `GET /rest/repositories/<id>`. Its `params` hold
    `ruleset`, whose `value` is the ruleset's name, for example `rdfsplus-optimized`. The name
    is returned without surrounding white space. `None` means the configuration has no ruleset
    value: no `params`, no `ruleset` in them, or a value that is not a non-empty string.
    """
    params = _params_of(configuration)
    if params is None:
        return None
    param = params.get("ruleset")
    if not isinstance(param, dict):
        return None
    value = param.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


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
        _raise_missing_dataset(store, response)
    if not response.ok:
        _raise_error_answer(
            store.logger,
            response,
            f"The store refused the probe of repository '{store._repository}'",
        )


class GraphDB(RDF4JClient):
    """
    The GraphDB adapter: a store of the contract `TripleStore`, on a GraphDB repository.

    Build it from a `TripleStoreEndpoint` and an auth provider, `GDBTokenAuth` or `BasicAuth`.
    `connect()` builds it so and checks it; code above the interface types it as
    `TripleStore`. It provides methods for querying and updating data, manages
    authentication, the dataset, and a default named graph.

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
        # No request: the provider logs in at the first one. Built from credentials, the
        # client checks the dataset and the named graph below, so it keeps neither yet.
        super().__init__(
            endpoint,
            auth,
            timeout=timeout,
            named_graph=named_graph if credentials is None else None,
            logger=logger,
            store_name="GraphDB",
        )
        self._credentials = credentials
        self._repositories: Optional[List[str]] = None

        if credentials is not None:
            self._auth = auth._authorization(self)
            self._repositories = self.datasets_get(only_ids=True)
            self.dataset = credentials.repository
            self.named_graph = named_graph
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

    # The deprecated names of data operations, which only this adapter keeps.
    from kapps_triplestore_interface.queries.named_graph import get_list_of_named_graphs
    from kapps_triplestore_interface.queries.rdf4j.graph_store import (
        fetch_statements,
        import_statements,
        clear_graph,
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
            TripleStoreUnavailableError: If the store gives no answer. When the store closed the
                connection without an answer, the login is sent once more, on a fresh
                connection, and raises only if that fails as well.
        """
        payload = {
            "username": username,
            "password": password,
        }
        # The login changes nothing in the store, so it is safe to send again, as a read is.
        response = self._make_request(
            "post",
            "rest/login",
            authenticate=False,
            retry_after_idle_close=True,
            json=payload,
        )
        if response.status_code == 200:
            return response.headers.get("Authorization")

        _raise_error_answer(self.logger, response, "Failed to obtain a GDB token")

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

    def _graph_store_address(self) -> str:
        """The address of the dataset's graph store, where the shapes graph is read and set."""
        return f"repositories/{self._repository}/rdf-graphs/service"

    def _require_shacl_validation(self, verb: str) -> None:
        """Raise `TripleStoreNotSupportedError` unless the repository's configuration says that
        SHACL validation is on. `verb` is what the caller cannot do with the shapes: "set" or
        "read".

        Raises:
            TripleStoreNotSupportedError: If the configuration says that SHACL validation is
                off, or does not say. The message names the repository.
            The error of `_repository_configuration` if the configuration cannot be read.
        """
        validation = _shacl_validation_on(self._repository_configuration())
        if validation is True:
            return
        reason = (
            "does not say whether SHACL validation is on"
            if validation is None
            else "says that SHACL validation is off"
        )
        raise TripleStoreNotSupportedError(
            f"Cannot {verb} the SHACL shapes of repository '{self._repository}': its"
            f" configuration {reason}. A repository gets SHACL validation only when it is"
            " created."
        )

    def shapes_get(self) -> Graph:
        """The SHACL shapes that the store validates the dataset's writes against, as a graph.

        It is the read of what `shapes_set` writes: a document set and then read gives the same
        triples. A dataset without shapes gives an empty graph.

        The adapter first reads the repository's configuration, as `shapes_set` does, and raises
        `TripleStoreNotSupportedError` when it does not say that SHACL validation is on: such a
        dataset holds no shapes that validate anything, and the shapes graph is then plain data.
        Then it reads RDF4J's shapes graph, `rdf4j:SHACLShapeGraph`, in one GET on the graph
        store, as Turtle.

        Limit: only that one graph is read, the one that `shapes_set` writes. A repository
        configured with further shapes graphs validates against those as well, and their shapes
        are not in the answer.

        Returns:
            Graph: The shapes, of the type that `graph_get` gives.

        Raises:
            TripleStoreNotSupportedError: If the configuration does not say that the dataset has
                SHACL validation. The shapes graph is not read.
            AuthenticationError: If the store answers 401.
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status. The
                message names the repository.
            TripleStoreUnavailableError: If a request gets no answer. When the store closed the
                connection without an answer, the read is sent once more, on a fresh
                connection, and raises only if that fails as well.
        """
        self._require_shacl_validation("read")
        response = self._make_request(
            "get",
            self._graph_store_address(),
            params=_SHAPES_GRAPH_PARAMS,
            headers={"Accept": "text/turtle"},
            retry_after_idle_close=True,
        )
        if not response.ok:
            _raise_error_answer(
                self.logger,
                response,
                f"Failed to read the SHACL shapes of repository '{self._repository}'",
            )
        shapes = Graph()
        if response.text.strip():
            shapes.parse(data=response.text, format="turtle")
        return shapes

    def ruleset_get(self) -> Optional[str]:
        """The reasoning ruleset of the dataset, as GraphDB names it, or `None`.

        For example `"rdfsplus-optimized"`, `"owl2-rl"` or `"owl-max"`. The adapter reads the
        `ruleset` parameter of the repository's configuration, the request that `shapes_set`
        sends first. `None` means the configuration has no ruleset value. The method reports;
        which rulesets a caller supports is the caller's rule.

        Raises:
            InvalidDatasetError: If the store answers 404 with `Unknown repository: <dataset>`.
            TripleStoreResponseError: For any other error answer, typed by its status as every
                configuration read is, also a 404 with another answer.
            TripleStoreUnavailableError: If the store gives no answer.
        """
        return _ruleset_of(self._repository_configuration())

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
        self._require_shacl_validation("set")
        graph = _SHAPES_GRAPH_PARAMS
        address = self._graph_store_address()
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

    def validate(self, shapes: str, content_type: str) -> str:
        """Validate the whole dataset against `shapes` and return the store's report verbatim.

        `shapes` is a SHACL shapes document of the media type `content_type`, for example
        `text/turtle`. One POST to GraphDB's validation endpoint,
        `rest/repositories/<repository>/validate/text`, with `shapes` as the body and
        `Accept: text/turtle`. The report's format is the store's: Turtle on GraphDB. The
        adapter returns the answer's text unchanged; a conforming dataset gives a report with
        `sh:conforms true`, and a violation is part of the report, not an error.

        An empty document, or one of white space only, validates against no shapes, and the
        report conforms.

        This operation never changes the dataset, and never the shapes that the store
        validates writes against. The dataset need not have SHACL validation turned on.

        Raises:
            InvalidDatasetError: If the store answers 404: the dataset does not exist.
            AuthenticationError: If the store answers 401.
            TripleStoreAccessError: If the store answers 403.
            TripleStoreResponseError: If the store answers with any other error status, for
                example to a document that it cannot parse. The message names the repository.
            TripleStoreUnavailableError: If a request gets no answer.
        """
        response = self._make_request(
            "post",
            f"rest/repositories/{self._repository}/validate/text",
            headers={"Content-Type": content_type, "Accept": "text/turtle"},
            # GraphDB 10.8.5 answers 400 to a request with an empty body, but validates a
            # document of white space against no shapes. An empty document is sent as a newline.
            data=(shapes if shapes.strip() else "\n").encode("utf-8"),
            retry_after_idle_close=True,
        )
        if response.status_code == 404:
            _raise_missing_dataset(self, response)
        if not response.ok:
            _raise_error_answer(
                self.logger,
                response,
                f"Failed to validate repository '{self._repository}'",
            )
        return response.text
