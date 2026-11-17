"""Access to the triple store of a Kadi instance."""

from __future__ import annotations

import configparser
import logging
import os
import re
import warnings
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import requests
from rdflib import Graph, Namespace

from kapps_triplestore_interface.exceptions import (
    InvalidDatasetError,
    TripleStoreNotSupportedError,
    TripleStoreResponseError,
    TripleStoreUnavailableError,
)
from kapps_triplestore_interface.rdf4j_client import (
    _NO_ANSWER,
    RDF4JClient,
    _carries_validation_report,
    _raise_error_answer,
)
from kapps_triplestore_interface.sparql_query import SPARQLQuery
from kapps_triplestore_interface.store import TripleStore, TripleStoreEndpoint
from kapps_triplestore_interface.utils.iri import IRI
from kapps_triplestore_interface.utils.types import (
    GraphName,
    GraphNameLike,
    IRILike,
    ObjectLike,
    PartialTripleLike,
    Predicate,
    PredicateLike,
    Subject,
    SubjectLike,
    TripleLike,
    TriplesLike,
)

# The config file with the host and personal access token of each Kadi instance. `None` is
# `~/.kadiconfig`, resolved only when the file is read, so that the import needs no home
# directory.
KADI_CONFIG_PATH: Optional[Path] = None

# The data operations of the store contract that are passed on to Kadi.
FORWARDED_OPERATIONS = (
    "query",
    "triple_exists",
    "triple_add",
    "triple_delete",
    "triples_get",
    "triples_add",
    "triples_delete",
    "triples_update",
    "iri_exists",
    "new_iri",
    "is_subclass",
    "owl_get_classes_of_individual",
    "graph_get",
    "graph_add",
    "graph_clear",
)

_API_PATH = "api/triple-store"

_TIMEOUT = 60

# A repository name has to be a single segment of a URL path.
_REPOSITORY_NAME = re.compile(r"[^/?#\s]+")


class KadiPATAuth:  # pylint: disable=too-few-public-methods
    """Authentication via a personal access token of Kadi.

    The token is sent as bearer token with each request. Since it cannot be renewed, a
    request that is answered with status 401 raises an :class:`.AuthenticationError`
    directly.

    :param pat: The personal access token. Its scopes ``triple_store.read`` and
        ``triple_store.write`` determine whether it may read and write.
    """

    def __init__(self, pat: str):
        self._header = f"Bearer {pat}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    # pylint: disable=unused-argument

    def _authorization(self, store: Optional[RDF4JClient]) -> Optional[str]:
        return self._header

    def _renew(
        self, store: Optional[RDF4JClient], refused: Optional[str]
    ) -> Optional[str]:
        return None

    # pylint: enable=unused-argument


# The message of a validation report with status 409, which refuses the data of a request.
_NOT_CONFORMING = (
    "409 Conflict: The data does not conform to the SHACL shapes of the triple store."
)


def _status_line_message(response: requests.Response) -> Optional[str]:
    """`<status> <reason>: <description>` for an error answer that states its reason.

    Such an answer is in JSON, of the form
    `{"code": 403, "message": "Forbidden", "description": "..."}`. The reason is its
    `message`, else the standard phrase of the status. The scopes that a token lacks follow
    the description, when the answer names them. A validation report with status 409 refuses
    the data of the request: `409 Conflict: The data does not conform to the SHACL shapes of
    the triple store.` Any other answer gives `None`.
    """
    refused = response.status_code == HTTPStatus.CONFLICT
    if refused and _carries_validation_report(response):
        return _NOT_CONFORMING
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or not isinstance(body.get("description"), str):
        return None
    reason = body.get("message")
    if not isinstance(reason, str) or not reason:
        try:
            reason = HTTPStatus(response.status_code).phrase
        except ValueError:
            reason = "Error"
    sentence = body["description"]
    scopes = body.get("scopes")
    if isinstance(scopes, list) and scopes:
        sentence += f" Required scope: {', '.join(str(scope) for scope in scopes)}."
    return f"{response.status_code} {reason}: {sentence}"


class _KadiClient(RDF4JClient):
    """Client of the triple store API of Kadi."""

    # Kadi is not known to negotiate an RDF answer to a CONSTRUCT or DESCRIBE, so a read
    # offers the JSON result format alone, as before.
    _READ_ACCEPT = "application/sparql-results+json"

    def _error_message(self, response: requests.Response) -> Optional[str]:
        return _status_line_message(response)

    def _query_failure(self, update: bool) -> str:
        return f"Could not run the {'update' if update else 'query'} through Kadi"


class KadiTripleStore(TripleStore):
    """A triple store that is accessed via the triple store API of a Kadi instance.

    Provides the data operations of :class:`.TripleStore`. The prefix and shapes
    registries as well as the validation of the whole dataset are not provided by Kadi and
    raise a :class:`.TripleStoreNotSupportedError`.

    Should be created via :func:`connect_kadi`.

    :param endpoint: The URL of the triple store API and the name of its repository.
    :param auth: The authentication via a personal access token.
    :param timeout: (optional) The timeout of the requests in seconds.
    :param named_graph: (optional) The default named graph.
    :param logger: (optional) The logger to use.
    """

    def __init__(
        self,
        endpoint: TripleStoreEndpoint,
        auth: KadiPATAuth,
        timeout: int = _TIMEOUT,
        named_graph: Optional[GraphNameLike] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.logger = (
            logger if logger is not None else logging.getLogger(type(self).__name__)
        )
        self._client = _KadiClient(
            endpoint, auth, timeout=timeout, named_graph=named_graph, logger=self.logger
        )

    @property
    def dataset(self) -> str:
        """The name of the repository that Kadi provides.

        :raises TripleStoreNotSupportedError: If another repository is set.
        """
        return self._client.dataset

    @dataset.setter
    def dataset(self, value: str) -> None:
        raise TripleStoreNotSupportedError(
            f"The repository of {type(self).__name__} cannot be changed to '{value}'."
        )

    @property
    def named_graph(self) -> Optional[GraphName]:
        """The default named graph, or ``None``."""
        return self._client.named_graph

    @named_graph.setter
    def named_graph(self, value: Optional[GraphNameLike]) -> None:
        self._client.named_graph = value

    def graphs_get(self) -> List[GraphNameLike]:
        """Get all named graphs that the user of the token may read.

        :return: The named graphs.
        """
        return self._client.graphs_get()

    def close(self) -> None:
        """Close all connections of the store."""
        self._client.close()

    def query(
        self,
        query: Union[SPARQLQuery, str],
        update: Optional[bool] = False,
        convert_bindings: Optional[bool] = False,
    ) -> Union[Dict, bool, Graph]:
        """See :meth:`.TripleStore.query`.

        A read offers Kadi the JSON result format alone: whether Kadi answers a CONSTRUCT or
        DESCRIBE with RDF is not verified, so neither is claimed here.
        """
        return self._client.query(
            query=query, update=update, convert_bindings=convert_bindings
        )

    def triple_exists(
        self,
        triple: TripleLike,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool:
        """See :meth:`.TripleStore.triple_exists`."""
        return self._client.triple_exists(triple=triple, named_graph=named_graph)

    def triple_add(
        self,
        triple: TripleLike,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool:
        """See :meth:`.TripleStore.triple_add`."""
        return self._client.triple_add(triple=triple, named_graph=named_graph)

    def triple_delete(
        self,
        triple: TripleLike,
        check_exist: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool:
        """See :meth:`.TripleStore.triple_delete`."""
        return self._client.triple_delete(
            triple=triple, check_exist=check_exist, named_graph=named_graph
        )

    def triples_get(
        self,
        triple: Optional[PartialTripleLike] = None,
        sub: Optional[SubjectLike] = None,
        pred: Optional[PredicateLike] = None,
        obj: Optional[ObjectLike] = None,
        include_explicit: Optional[bool] = True,
        include_implicit: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
    ) -> List[Tuple[Subject, Predicate, Any]]:
        """See :meth:`.TripleStore.triples_get`."""
        return self._client.triples_get(
            triple=triple,
            sub=sub,
            pred=pred,
            obj=obj,
            include_explicit=include_explicit,
            include_implicit=include_implicit,
            named_graph=named_graph,
        )

    def triples_add(
        self,
        triples_to_add: TriplesLike,
        check_exist: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
        absent_subjects: Optional[List[SubjectLike]] = None,
    ) -> bool:
        """See :meth:`.TripleStore.triples_add`."""
        return self._client.triples_add(
            triples_to_add=triples_to_add,
            check_exist=check_exist,
            named_graph=named_graph,
            absent_subjects=absent_subjects,
        )

    def triples_delete(
        self,
        triples_to_delete: TriplesLike,
        check_exist: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool:
        """See :meth:`.TripleStore.triples_delete`."""
        return self._client.triples_delete(
            triples_to_delete=triples_to_delete,
            check_exist=check_exist,
            named_graph=named_graph,
        )

    def triples_update(
        self,
        old_triples: TriplesLike,
        new_triples: TriplesLike,
        check_exist: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
        absent_subjects: Optional[List[SubjectLike]] = None,
        present_triples: Optional[TriplesLike] = None,
    ) -> bool:
        """See :meth:`.TripleStore.triples_update`."""
        return self._client.triples_update(
            old_triples=old_triples,
            new_triples=new_triples,
            check_exist=check_exist,
            named_graph=named_graph,
            absent_subjects=absent_subjects,
            present_triples=present_triples,
        )

    def iri_exists(
        self,
        iri: IRILike,
        as_sub: Optional[bool] = False,
        as_pred: Optional[bool] = False,
        as_obj: Optional[bool] = False,
        include_explicit: Optional[bool] = True,
        include_implicit: Optional[bool] = True,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool:
        """See :meth:`.TripleStore.iri_exists`."""
        return self._client.iri_exists(
            iri=iri,
            as_sub=as_sub,
            as_pred=as_pred,
            as_obj=as_obj,
            include_explicit=include_explicit,
            include_implicit=include_implicit,
            named_graph=named_graph,
        )

    def new_iri(
        self,
        base: IRILike,
        schema: Optional[Callable[[IRI], IRI]] = None,
        test_schema: bool = True,
    ) -> IRI:
        """See :meth:`.TripleStore.new_iri`."""
        return self._client.new_iri(base=base, schema=schema, test_schema=test_schema)

    def is_subclass(
        self,
        subclass_iri: IRILike,
        class_iri: IRILike,
        named_graph: Optional[GraphNameLike] = None,
    ) -> bool:
        """See :meth:`.TripleStore.is_subclass`."""
        return self._client.is_subclass(
            subclass_iri=subclass_iri, class_iri=class_iri, named_graph=named_graph
        )

    def owl_get_classes_of_individual(
        self,
        instance_iri: IRILike,
        ignored_prefixes: Optional[List[Union[str, Namespace]]] = None,
        local_name: Optional[bool] = False,
        include_explicit: Optional[bool] = True,
        include_implicit: Optional[bool] = False,
        named_graph: Optional[GraphNameLike] = None,
    ) -> List[Union[IRI, str]]:
        """See :meth:`.TripleStore.owl_get_classes_of_individual`."""
        return self._client.owl_get_classes_of_individual(
            instance_iri=instance_iri,
            ignored_prefixes=ignored_prefixes,
            local_name=local_name,
            include_explicit=include_explicit,
            include_implicit=include_implicit,
            named_graph=named_graph,
        )

    def graph_get(
        self,
        graph_iri: Optional[GraphNameLike] = None,
    ) -> Graph:
        """See :meth:`.TripleStore.graph_get`."""
        return self._client.graph_get(graph_iri=graph_iri)

    def graph_add(
        self,
        content: str,
        overwrite: Optional[bool] = False,
        graph_iri: Optional[GraphNameLike] = None,
        content_type: Optional[str] = "application/x-turtle",
    ) -> bool:
        """See :meth:`.TripleStore.graph_add`."""
        return self._client.graph_add(
            content=content,
            overwrite=overwrite,
            graph_iri=graph_iri,
            content_type=content_type,
        )

    def graph_clear(
        self,
        graph_iri: Optional[GraphNameLike] = None,
    ) -> bool:
        """See :meth:`.TripleStore.graph_clear`."""
        return self._client.graph_clear(graph_iri=graph_iri)


def connect_kadi(
    *,
    instance: Optional[str] = None,
    host: Optional[str] = None,
    pat: Optional[str] = None,
) -> KadiTripleStore:
    """Connect to the triple store of a Kadi instance.

    The host and personal access token can either be passed directly or are read from the
    config file ``~/.kadiconfig``, using the given or the default instance::

        [global]
        default = my_instance

        [my_instance]
        host = https://kadi.example.org
        pat = <personal access token>

    :param instance: (optional) The name of an instance in the config file.
    :param host: (optional) The host of the Kadi instance, e.g.
        ``https://kadi.example.org``.
    :param pat: (optional) A personal access token with the scope ``triple_store.read``
        and/or ``triple_store.write``.
    :return: The triple store.
    :raises ValueError: If the config file is required but does not exist or is
        incomplete.
    :raises AuthenticationError: If the personal access token is invalid or lacks the
        required scope.
    :raises InvalidDatasetError: If the Kadi instance provides no triple store.
    :raises TripleStoreUnavailableError: If Kadi or its triple store cannot be reached.
    :raises TripleStoreResponseError: If Kadi answers with any other error or with no
        valid repository name.
    """
    host, pat = _read_config(instance, host, pat)
    host = host.rstrip("/")
    auth = KadiPATAuth(pat)
    url = f"{host}/{_API_PATH}"
    logger = logging.getLogger(KadiTripleStore.__name__)

    try:
        response = requests.get(
            url, headers={"Authorization": auth._authorization(None)}, timeout=_TIMEOUT
        )
    except _NO_ANSWER as error:
        raise TripleStoreUnavailableError(
            f"Could not connect to Kadi at {host}: {error}"
        ) from error

    if response.status_code == 404:
        message = f"Kadi at {host} provides no triple store."
        logger.error(message)
        raise InvalidDatasetError(message)

    if response.status_code == 503:
        message = f"The triple store of Kadi at {host} is not available."
        logger.error(message)
        raise TripleStoreUnavailableError(message)

    if not response.ok:
        _raise_error_answer(
            logger,
            response,
            f"Could not connect to the triple store of Kadi at {host}",
            _status_line_message(response),
        )

    repository = _get_repository_name(response)

    if repository is None:
        message = f"Kadi at {host} returned no valid repository name."
        logger.error(message)
        raise TripleStoreResponseError(message, status=response.status_code)

    # Kadi already checked the token and the triple store, so no further request is sent.
    store = KadiTripleStore(TripleStoreEndpoint(url=url, dataset=repository), auth)
    store.logger.info(f"Connected to repository '{repository}' of Kadi at {host}.")

    return store


def _read_config(
    instance: Optional[str], host: Optional[str], pat: Optional[str]
) -> Tuple[str, str]:
    if instance is None and host and pat:
        return host, pat

    config_path = KADI_CONFIG_PATH or Path.home().joinpath(".kadiconfig")

    if not config_path.is_file():
        raise ValueError(
            f"Config file does not exist at '{config_path}'. Pass a host and personal"
            " access token or create the config file."
        )

    if os.name == "posix" and config_path.stat().st_mode & 0o777 != 0o600:
        warnings.warn(
            "It is recommended to keep the permissions of the config file at"
            f" '{config_path}' restrictive (read/write for the file owner only).",
            stacklevel=3,
        )

    config = configparser.ConfigParser()

    try:
        config.read(config_path)
    except configparser.Error as error:
        raise ValueError(f"Error during parsing of config file:\n{error}") from error

    if instance is None:
        instance = config.get("global", "default", fallback=None)

        if not instance:
            raise ValueError(
                f"No default instance defined in the config file at '{config_path}'."
            )

    if instance == "global" or not config.has_section(instance):
        raise ValueError(
            f"Instance '{instance}' is not defined in the config file at"
            f" '{config_path}'."
        )

    host = host or config.get(instance, "host", fallback=None)
    pat = pat or config.get(instance, "pat", fallback=None)

    for key, value in (("host", host), ("pat", pat)):
        if not value:
            raise ValueError(
                f"Please define the key '{key}' for instance '{instance}' in the config"
                " file."
            )

    return host, pat


def _get_repository_name(response: requests.Response) -> Optional[str]:
    try:
        body = response.json()
    except ValueError:
        return None

    repository = body.get("name") if isinstance(body, dict) else None

    if not isinstance(repository, str) or not _REPOSITORY_NAME.fullmatch(repository):
        return None

    return repository
