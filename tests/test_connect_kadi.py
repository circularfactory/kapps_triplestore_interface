"""Tests of the access to the triple store of a Kadi instance.

A stub stands in for Kadi, see `_stub_store.py`; each test sets the answers that it needs.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from kapps_triplestore_interface import (
    AuthenticationError,
    BasicAuth,
    GraphDB,
    KadiTripleStore,
    KadiPATAuth,
    ShaclValidationError,
    TripleStoreAccessError,
    TripleStore,
    TripleStoreNotSupportedError,
    TripleStoreResponseError,
    TripleStoreEndpoint,
    TripleStoreUnavailableError,
    connect_kadi,
)
from kapps_triplestore_interface import kadi as kadi_module
from kapps_triplestore_interface.exceptions import InvalidDatasetError
from kapps_triplestore_interface.queries.checked_write import RECEIPT_GRAPH
from kapps_triplestore_interface.rdf4j_client import RDF4JClient
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    answer,
    store,
)

PAT = "pat_not-a-real-token"
BEARER = f"Bearer {PAT}"
NAME = "my-repository"
API = "/api/triple-store"
QUERY = f"{API}/repositories/{NAME}"
UPDATE = f"{QUERY}/statements"


@pytest.fixture(name="kadi")
def fixture_kadi(store):  # pylint: disable=redefined-outer-name
    """The stub answers as a Kadi instance whose triple store has the dataset `NAME`."""
    store.answers[API] = answer(200, json.dumps({"name": NAME}), "application/json")
    return store


@pytest.fixture(name="kadi_config")
def fixture_kadi_config(tmp_path, monkeypatch):
    """Writes the config file and points to it."""
    path = tmp_path / ".kadiconfig"
    monkeypatch.setattr(kadi_module, "KADI_CONFIG_PATH", path)

    def write(text: str, mode: int = 0o600):
        path.write_text(textwrap.dedent(text))
        path.chmod(mode)

    write(
        f"""
        [global]
        default = dev

        [dev]
        host = {BASE_URL}
        pat = {PAT}

        [other]
        host = {BASE_URL}/
        pat = pat_of-other
        """
    )
    return write


# -- the way to the store ----------------------------------------------------------------------


def test_kadi_names_the_dataset_and_no_probe_follows(kadi):
    connected = connect_kadi(host=BASE_URL, pat=PAT)

    assert isinstance(connected, KadiTripleStore)
    assert connected.dataset == NAME
    assert kadi.sent == [("GET", API, BEARER)]


def test_every_request_carries_the_token_and_nothing_logs_in(kadi):
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    connected.query("ASK { ?s ?p ?o }")

    assert kadi.paths() == [API, QUERY]
    assert {authorization for _, _, authorization in kadi.sent} == {BEARER}


def test_a_write_only_token_connects_and_writes_without_reading(kadi):
    """Kadi refuses reads to a token with only `triple_store.write`, so nothing may read."""
    kadi.method_answers[("POST", QUERY)] = answer(
        401,
        json.dumps({"description": "Access token has insufficient scope."}),
        "application/json",
    )
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    connected.query(
        "INSERT DATA { GRAPH <urn:g> { <urn:s> <urn:p> <urn:o> } }", update=True
    )

    assert kadi.paths() == [API, UPDATE]


def test_a_trailing_slash_of_the_host_is_ignored(kadi):
    connect_kadi(host=BASE_URL + "/", pat=PAT)

    assert kadi.paths() == [API]


@pytest.mark.usefixtures("kadi_config")
def test_without_arguments_the_default_instance_of_the_config_file_is_used(kadi):
    connect_kadi()

    assert kadi.sent == [("GET", API, BEARER)]


@pytest.mark.usefixtures("kadi_config")
def test_a_named_instance_of_the_config_file_is_used(kadi):
    connect_kadi(instance="other")

    assert kadi.sent == [("GET", API, "Bearer pat_of-other")]


@pytest.mark.usefixtures("kadi_config")
def test_an_argument_wins_over_the_config_file(kadi):
    connect_kadi(instance="other", pat=PAT)

    assert kadi.sent == [("GET", API, BEARER)]


def test_host_and_pat_need_no_config_file(kadi, monkeypatch, tmp_path):
    monkeypatch.setattr(kadi_module, "KADI_CONFIG_PATH", tmp_path / "missing")

    connect_kadi(host=BASE_URL, pat=PAT)

    assert kadi.sent == [("GET", API, BEARER)]


@pytest.mark.parametrize(
    "text, message",
    [
        ("[dev]\nhost = h\npat = p\n", "No default instance defined"),
        (
            "[global]\ndefault = prod\n[dev]\nhost = h\npat = p\n",
            "Instance 'prod' is not defined",
        ),
        (
            "[global]\ndefault = dev\n[dev]\npat = p\n",
            "define the key 'host' for instance 'dev'",
        ),
        (
            "[global]\ndefault = dev\n[dev]\nhost = h\npat =\n",
            "define the key 'pat' for instance 'dev'",
        ),
        ("not an ini file", "Error during parsing of config file"),
    ],
    ids=["no-default", "unknown-instance", "no-host", "empty-pat", "unparsable"],
)
def test_a_config_file_without_what_is_needed_is_named_before_any_request(
    kadi, kadi_config, text, message
):
    kadi_config(text)

    with pytest.raises(ValueError, match=message):
        connect_kadi()
    assert not kadi.sent


def test_a_missing_config_file_is_named(kadi, monkeypatch, tmp_path):
    monkeypatch.setattr(kadi_module, "KADI_CONFIG_PATH", tmp_path / "missing")

    with pytest.raises(ValueError, match="does not exist"):
        connect_kadi(instance="dev")
    assert not kadi.sent


def test_a_config_file_that_others_may_read_warns(kadi, kadi_config):
    kadi_config(
        f"[global]\ndefault = dev\n[dev]\nhost = {BASE_URL}\npat = {PAT}\n", 0o644
    )

    with pytest.warns(UserWarning, match="restrictive"):
        connect_kadi()
    assert kadi.sent == [("GET", API, BEARER)]


def test_the_config_file_is_looked_up_in_the_home_directory_when_it_is_read(
    kadi, monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / ".kadiconfig"
    path.write_text(f"[global]\ndefault = dev\n[dev]\nhost = {BASE_URL}\npat = {PAT}\n")
    path.chmod(0o600)

    connect_kadi()

    assert kadi.sent == [("GET", API, BEARER)]


def test_the_import_needs_no_home_directory():
    """Where no home directory resolves, `Path.home()` raises; the import does not call it."""
    code = (
        "import pathlib\n"
        "def no_home(cls):\n"
        "    raise RuntimeError('Could not determine home directory.')\n"
        "pathlib.Path.home = classmethod(no_home)\n"
        "import kapps_triplestore_interface\n"
    )
    package_root = Path(kadi_module.__file__).parent.parent
    env = {**os.environ, "PYTHONPATH": str(package_root)}

    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


# -- what Kadi answers -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body, media_type",
    [
        ("{}", "application/json"),
        ("[]", "application/json"),
        (json.dumps({"name": 5}), "application/json"),
        (json.dumps({"name": ""}), "application/json"),
        (json.dumps({"name": "a/b"}), "application/json"),
        (json.dumps({"name": "a b"}), "application/json"),
        ("<html><body>Login</body></html>", "text/html"),
    ],
    ids=["empty", "list", "number", "blank", "slash", "space", "html"],
)
def test_an_answer_without_a_valid_dataset_raises_a_response_error(
    kadi, body, media_type
):
    kadi.answers[API] = answer(200, body, media_type)

    with pytest.raises(
        TripleStoreResponseError, match="no valid repository name"
    ) as error:
        connect_kadi(host=BASE_URL, pat=PAT)
    assert error.value.status == 200
    assert kadi.paths() == [API]


def test_a_refused_token_raises_authentication_without_a_second_try(kadi):
    kadi.answers[API] = answer(
        401,
        json.dumps({"description": "Access token has insufficient scope."}),
        "application/json",
    )

    with pytest.raises(AuthenticationError, match="insufficient scope"):
        connect_kadi(host=BASE_URL, pat=PAT)
    assert kadi.paths() == [API]


def test_a_token_revoked_after_connect_raises_authentication_at_once(kadi):
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    kadi.answers[QUERY] = answer(401, "Unauthorized")

    with pytest.raises(AuthenticationError):
        connected.query("ASK { ?s ?p ?o }")
    assert kadi.paths() == [API, QUERY]


def test_a_user_who_may_read_no_graph_is_refused_at_the_first_read(kadi):
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    kadi.answers[QUERY] = answer(
        403,
        json.dumps({"description": "You do not have permission to read any graph."}),
        "application/json",
    )

    with pytest.raises(TripleStoreAccessError, match="read any graph"):
        connected.query("ASK { ?s ?p ?o }")


@pytest.mark.parametrize(
    "body, expected",
    [
        (
            {
                "code": 403,
                "message": "Forbidden",
                "description": "You do not have permission to read the graph <urn:b>.",
            },
            "403 Forbidden: You do not have permission to read the graph <urn:b>.",
        ),
        (
            {
                "code": 401,
                "message": "Unauthorized",
                "description": "Access token has insufficient scope.",
                "scopes": ["triple_store.read"],
            },
            "401 Unauthorized: Access token has insufficient scope."
            " Required scope: triple_store.read.",
        ),
        (
            {
                "code": 403,
                "description": "You do not have permission to read any graph.",
            },
            "403 Forbidden: You do not have permission to read any graph.",
        ),
    ],
    ids=["denied", "scope", "no-reason"],
)
def test_an_error_is_kadis_status_line_and_description(kadi, body, expected):
    """An error answer of Kadi is shown as its status line and description."""
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    kadi.answers[QUERY] = answer(body["code"], json.dumps(body), "application/json")

    with pytest.raises(TripleStoreResponseError) as error:
        connected.query("ASK { ?s ?p ?o }")
    assert str(error.value) == expected
    assert error.value.status == body["code"]


def test_a_denied_update_is_kadis_status_line_and_description(kadi):
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    body = {
        "code": 403,
        "message": "Forbidden",
        "description": "You do not have permission to insert into the graph <urn:b>.",
    }
    kadi.answers[UPDATE] = answer(403, json.dumps(body), "application/json")

    with pytest.raises(TripleStoreAccessError) as error:
        connected.query(
            "INSERT DATA { GRAPH <urn:b> { <urn:s> <urn:p> 1 } }", update=True
        )
    assert str(error.value) == (
        "403 Forbidden: You do not have permission to insert into the graph <urn:b>."
    )


@pytest.mark.parametrize(
    "path, write",
    [
        (
            UPDATE,
            lambda store: store.query(
                "INSERT DATA { GRAPH <urn:a> { <urn:s> <urn:p> 1 } }", update=True
            ),
        ),
        (
            f"{QUERY}/rdf-graphs/service",
            lambda store: store.graph_add(
                "<urn:s> <urn:p> 1 .", graph_iri="http://example.org/g"
            ),
        ),
    ],
    ids=["update", "graph"],
)
def test_data_refused_by_shacl_is_a_status_line_and_keeps_the_report(kadi, path, write):
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    report = (
        "_:report <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
        " <http://www.w3.org/ns/shacl#ValidationReport> .\n"
    )
    kadi.answers[path] = answer(
        409, report, "application/shacl-validation-report+n-quads"
    )

    with pytest.raises(ShaclValidationError) as error:
        write(connected)
    assert str(error.value) == (
        "409 Conflict: The data does not conform to the SHACL shapes of the triple store."
    )
    assert error.value.report == report
    assert error.value.status == 409


def test_a_refused_connection_is_kadis_status_line_and_description(kadi):
    kadi.answers[API] = answer(
        401,
        json.dumps(
            {
                "code": 401,
                "message": "Unauthorized",
                "description": "No valid access token was supplied.",
            }
        ),
        "application/json",
    )

    with pytest.raises(AuthenticationError) as error:
        connect_kadi(host=BASE_URL, pat=PAT)
    assert str(error.value) == "401 Unauthorized: No valid access token was supplied."


def test_an_instance_without_a_triple_store_raises_invalid_dataset(kadi):
    kadi.answers[API] = answer(404, "Not Found")

    with pytest.raises(InvalidDatasetError, match="provides no triple store"):
        connect_kadi(host=BASE_URL, pat=PAT)
    assert kadi.paths() == [API]


def test_a_store_that_kadi_cannot_reach_raises_unavailable(kadi):
    kadi.answers[API] = answer(503, json.dumps({"description": "Unavailable."}))

    with pytest.raises(TripleStoreUnavailableError, match="is not available"):
        connect_kadi(host=BASE_URL, pat=PAT)


def test_a_failing_triple_store_api_keeps_its_status(kadi):
    kadi.answers[API] = answer(502, "Triple store configuration or backend failed.")

    with pytest.raises(TripleStoreResponseError) as error:
        connect_kadi(host=BASE_URL, pat=PAT)
    assert error.value.status == 502


def test_an_unreachable_kadi_raises_unavailable(kadi):
    kadi.unreachable = True

    with pytest.raises(
        TripleStoreUnavailableError, match="Could not connect to Kadi at"
    ):
        connect_kadi(host=BASE_URL, pat=PAT)


def test_graphdb_keeps_its_message_for_an_answer_with_a_description(store):
    """Only the Kadi client reads the status line: the shared client keeps its message."""
    body = json.dumps({"message": "Bad Request", "description": "Not a query."})
    store.answers[f"/repositories/{DATASET}"] = answer(400, body, "application/json")
    graph_db = GraphDB(
        endpoint=TripleStoreEndpoint(url=BASE_URL, dataset=DATASET),
        auth=BasicAuth(USERNAME, PASSWORD),
    )

    with pytest.raises(TripleStoreResponseError) as error:
        graph_db.query("ASK {}")
    assert str(error.value) == f"Error while querying GraphDB (400) - {body}"


# -- what Kadi does not expose ----------------------------------------------------------------


@pytest.mark.parametrize(
    "operation",
    [
        lambda store: store.prefixes_get(),
        lambda store: store.prefix_set("ex", "http://example.org/"),
        lambda store: store.prefix_delete("ex"),
        lambda store: store.shapes_get(),
        lambda store: store.shapes_set("", "text/turtle"),
        lambda store: store.validate("", "text/turtle"),
        lambda store: setattr(store, "dataset", "another"),
    ],
    ids=[
        "prefixes_get",
        "prefix_set",
        "prefix_delete",
        "shapes_get",
        "shapes_set",
        "validate",
        "dataset",
    ],
)
def test_an_operation_that_kadi_does_not_expose_is_not_supported(kadi, operation):
    connected = connect_kadi(host=BASE_URL, pat=PAT)

    with pytest.raises(TripleStoreNotSupportedError, match="KadiTripleStore"):
        operation(connected)
    assert kadi.paths() == [API]


def test_the_ruleset_is_unknown_without_a_request(kadi):
    connected = connect_kadi(host=BASE_URL, pat=PAT)

    assert connected.ruleset_get() is None
    assert kadi.paths() == [API]


# -- checked writes ----------------------------------------------------------------------------

GRAPH = "http://example.org/graph/data"
TRIPLE = ("http://example.org/s", "http://example.org/p", "http://example.org/o")
RECEIPT = re.compile(r"<(urn:uuid:[0-9a-f-]{36})>")


def _removal(receipt: str) -> str:
    return f"DELETE WHERE {{ GRAPH {RECEIPT_GRAPH.n3()} {{ <{receipt}> ?p ?o }} }}"


def test_a_checked_write_is_one_update_and_one_ask_through_kadi(kadi):
    """Kadi grants the update with Write on the graph and Append on the receipt graph, and the
    `ASK` with Read on the receipt graph."""
    connected = connect_kadi(host=BASE_URL, pat=PAT)

    assert connected.triples_add([TRIPLE], named_graph=GRAPH) is True

    assert kadi.paths() == [API, UPDATE, QUERY]
    update, ask = kadi.bodies[1], kadi.bodies[2]
    receipt = RECEIPT.search(update).group(1)
    assert update.startswith(f"WITH <{GRAPH}>\n")
    assert f"GRAPH {RECEIPT_GRAPH.n3()} {{ <{receipt}> " in update
    assert "USING" not in update
    assert ask == f"ASK {{ GRAPH {RECEIPT_GRAPH.n3()} {{ <{receipt}> ?p ?o }} }}"
    assert {authorization for _, _, authorization in kadi.sent} == {BEARER}


def test_the_next_checked_write_removes_the_last_receipt_through_kadi(kadi):
    """The removal deletes from the receipt graph, which Kadi grants only with Write."""
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    connected.triples_add([TRIPLE], named_graph=GRAPH)
    receipt = RECEIPT.search(kadi.bodies[1]).group(1)

    connected.triples_add([TRIPLE], named_graph=GRAPH)

    assert kadi.paths() == [API, UPDATE, QUERY, UPDATE, QUERY]
    assert _removal(receipt) in kadi.bodies[3]


def test_closing_removes_the_receipts_through_kadi(kadi):
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    connected.triples_add([TRIPLE], named_graph=GRAPH)
    receipt = RECEIPT.search(kadi.bodies[1]).group(1)

    connected.close()

    assert kadi.paths() == [API, UPDATE, QUERY, UPDATE]
    assert _removal(receipt) in kadi.bodies[3]


@pytest.mark.parametrize(
    "named_graph, sent, description",
    [
        (
            None,
            "USING <http://rdf4j.org/schema/rdf4j#nil>",
            "<http://rdf4j.org/schema/rdf4j#nil> is the store's default graph, which belongs"
            " to no one; use a named graph.",
        ),
        (
            GRAPH,
            f"WITH <{GRAPH}>",
            "You do not have permission to insert into the graph"
            " <urn:x-kapps:write-receipts>.",
        ),
    ],
    ids=["default-graph", "receipt-graph-not-granted"],
)
def test_kadi_refuses_a_checked_write_that_its_acl_does_not_allow(
    kadi, named_graph, sent, description
):
    """Kadi does not expose the default graph, and refuses an update with a graph that the ACL
    does not grant, before the store sees it. No `ASK` follows."""
    kadi.method_answers[("POST", UPDATE)] = answer(
        403,
        json.dumps({"code": 403, "message": "Forbidden", "description": description}),
        "application/json",
    )
    connected = connect_kadi(host=BASE_URL, pat=PAT)

    with pytest.raises(TripleStoreAccessError, match=re.escape(description)):
        connected.triples_add([TRIPLE], named_graph=named_graph)

    assert sent in kadi.bodies[1]
    assert kadi.paths() == [API, UPDATE]


# -- the store contract --------------------------------------------------

# The operations of the contract that Kadi does not expose: the contract's own definitions raise.
NOT_SUPPORTED = {
    "prefixes_get",
    "prefix_set",
    "prefix_delete",
    "shapes_get",
    "shapes_set",
    "validate",
}

# The operations whose default answer of the contract is right for Kadi: it does not say.
CONTRACT_DEFAULT = {"ruleset_get"}

# What the adapter defines itself besides the forwarded data operations.
OWN = {"dataset", "close"}


def _contract_operations() -> set[str]:
    return {name for name in vars(TripleStore) if not name.startswith("_")}


def test_each_contract_operation_is_forwarded_or_not_supported():
    """Each operation of the contract is forwarded, not supported or the contract's default."""
    contract = _contract_operations()
    defined = {name for name in contract if name in vars(KadiTripleStore)}
    forwarded = set(kadi_module.FORWARDED_OPERATIONS)

    assert defined == forwarded | OWN
    assert not defined & (NOT_SUPPORTED | CONTRACT_DEFAULT)
    assert defined | NOT_SUPPORTED | CONTRACT_DEFAULT == contract


@pytest.mark.parametrize("name", kadi_module.FORWARDED_OPERATIONS)
def test_a_forwarded_operation_has_the_contracts_signature_and_the_clients_parameters(
    name,
):
    contract = inspect.signature(getattr(TripleStore, name))
    assert inspect.signature(getattr(KadiTripleStore, name)) == contract

    client = inspect.signature(getattr(RDF4JClient, name)).parameters
    assert set(contract.parameters) <= set(client)


def test_the_store_provides_no_administration(kadi):
    connected = connect_kadi(host=BASE_URL, pat=PAT)

    assert not isinstance(connected, GraphDB)
    for name in (
        "datasets_get",
        "get_list_of_repositories",
        "repository",
        "from_env",
        "fetch_statements",
        "_get_authentication_token",
    ):
        assert not hasattr(connected, name), name
    assert kadi.paths() == [API]


def test_a_data_operation_goes_through_kadi(kadi):
    kadi.answers[QUERY] = answer(
        200,
        json.dumps({"head": {"vars": ["g"]}, "results": {"bindings": []}}),
        "application/sparql-results+json",
    )
    connected = connect_kadi(host=BASE_URL, pat=PAT)

    assert connected.graphs_get() == []
    assert connected.triples_get(sub="http://example.org/s") == []
    assert kadi.paths() == [API, QUERY, QUERY]


# -- the provider ------------------------------------------------------------------------------


def test_the_provider_never_shows_its_token():
    assert repr(KadiPATAuth(PAT)) == "KadiPATAuth()"


def test_the_token_is_a_bearer_token_that_cannot_be_renewed():
    provider = KadiPATAuth(PAT)

    assert provider._authorization(None) == BEARER  # pylint: disable=protected-access
    assert provider._renew(None, BEARER) is None  # pylint: disable=protected-access


def test_the_arguments_are_keywords_only(kadi):
    with pytest.raises(TypeError):
        connect_kadi(BASE_URL, PAT)  # pylint: disable=too-many-function-args
    assert not kadi.sent
