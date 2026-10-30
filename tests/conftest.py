"""Shared pytest fixtures.

This is an integration suite. Most of its tests drive a real GraphDB, because that is the
thing this library exists to wrap and a mock of it would only assert that the mock was called.
CI provisions a disposable GraphDB for them, so the whole suite runs there. A checkout
without a triple store runs the tests that need none and skips the rest, which is a report
of what was not run rather than a claim that it passed.

The four ``TRIPLESTORE_*`` variables below select the store, and `db` builds it with
``connect()`` and the GDB token, as an application does. The suite wipes what it connects to,
so they must not point at anything of value; CI points them at a dataset it created empty
inside the job and destroys with the job. The deprecated ``GRAPHDB_*`` names still work
for the package, but the suite does not read them.

An instruction to point them somewhere harmless is not protection. `db` refuses any target it
cannot tell is disposable. See ``is_disposable_target`` below for what
disposable means and for the one variable that overrides it.
"""

import os
from typing import cast
from urllib.parse import urlsplit

import pytest
from kapps_triplestore_interface import (
    GDBTokenAuth,
    GraphDB,
    TripleStoreEndpoint,
    connect,
)

REQUIRED_ENV = (
    "TRIPLESTORE_URL",
    "TRIPLESTORE_USERNAME",
    "TRIPLESTORE_PASSWORD",
    "TRIPLESTORE_TEST_DATASET",
)

# A fixture that destroys data must be **told** its target is disposable rather than infer the
# permission from a URL being set. `TRIPLESTORE_TEST_DATASET` names the intent but asserts
# nothing: it is an ordinary environment variable holding whatever the shell last exported, and
# the fixture wiped whatever came back.
#
# Disposable means one of exactly two things:
#
# - **The host is loopback, or a bare hostname carrying no dot.** A bare name is a container
#   alias -- `graphdb`, which is this project's CI service alias -- and it resolves only inside
#   the network that defines it. A store that other people share is always reached by a dotted
#   name. The rule needs no allowlist and no upkeep.
#
#   The institute's shared store is the dotted name this matters for, and it is deliberately
#   not written here: `tests/` ships, and check 4 in `scripts/release_checks.py` rejects a
#   private host anywhere in the public tree. The tests use `example.org` for the same reason.
# - **`TRIPLESTORE_ALLOW_DESTRUCTIVE=1` is set**, which is a person saying so in as many words.
ALLOW_DESTRUCTIVE_ENV = "TRIPLESTORE_ALLOW_DESTRUCTIVE"

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_disposable_target(url: str | None) -> bool:
    """Whether wiping the store at ``url`` is safe by construction rather than by habit.

    A URL this cannot parse a host out of is **not** disposable. The failure direction matters:
    every uncertain case must land on refusal, because the cost of a wrong `False` is a skipped
    test run and the cost of a wrong `True` is somebody else's data.
    """
    host = (urlsplit(url or "").hostname or "").lower()
    if not host:
        return False
    return host in LOOPBACK_HOSTS or "." not in host


def pytest_collection_modifyitems(items):
    """Mark every test that reaches the triple store as ``live``.

    Derived from the fixture graph rather than written on each test, so the marker cannot drift
    out of step with what a test actually needs. ``item.fixturenames`` is the resolved closure,
    so a test that requests ``db`` through another fixture is marked as surely as one that
    names it. That transitive case is the one that gets missed by hand.

    ``-m "not live"`` then selects the tier that runs anywhere. CI does not pass that
    flag: it has a triple store and runs the whole suite.
    """
    for item in items:
        if "db" in item.fixturenames:
            item.add_marker("live")


@pytest.fixture(scope="session")
def db() -> GraphDB:
    """A GraphDB client from the environment, or skip.

    Skips rather than exits. The previous ``sys.exit(1)`` was not a skip but a hard collection
    failure: it reported 84 errors on a checkout whose only fault was having no triple store,
    and a real regression could not have been seen among them.
    """
    missing = [name for name in REQUIRED_ENV if os.getenv(name) is None]
    if missing:
        pytest.skip(f"needs a reachable GraphDB; unset: {', '.join(missing)}")

    url = os.getenv("TRIPLESTORE_URL")
    if not is_disposable_target(url) and os.getenv(ALLOW_DESTRUCTIVE_ENV) != "1":
        pytest.fail(
            f"refusing to clear graphs in dataset "
            f"{os.getenv('TRIPLESTORE_TEST_DATASET')!r} on {url!r}.\n"
            "This fixture wipes the default context and three named graphs at session start, and "
            "that host is neither loopback nor a container alias, so nothing here can tell that "
            "it is disposable.\n"
            "Point TRIPLESTORE_URL at a local GraphDB or a service alias, or set "
            f"{ALLOW_DESTRUCTIVE_ENV}=1 to state that the target is disposable.",
            pytrace=False,
        )

    db = cast(
        GraphDB,
        connect(
            TripleStoreEndpoint(
                url=url, dataset=os.environ["TRIPLESTORE_TEST_DATASET"]
            ),
            GDBTokenAuth.from_env(),
        ),
    )

    # `test_unknown_datatypes.py` writes into the third graph. A run that stops between a case's
    # setup and its teardown leaves a value there, and the next run would read two.
    for graph in [
        None,
        "http://example.org/named_graph",
        "http://example.org/local_named_graph",
        "http://example.org/unknown_datatypes_graph",
    ]:
        db.graph_clear(graph)

    return db


@pytest.fixture(scope="session")
def store_settings(db: GraphDB) -> dict[str, str]:
    """The URL, identity and dataset of the suite's store, read from the ``TRIPLESTORE_*``
    variables, for the tests whose subject is a client built another way than `connect()`.
    """
    return {
        "base_url": os.environ["TRIPLESTORE_URL"],
        "username": os.environ["TRIPLESTORE_USERNAME"],
        "password": os.environ["TRIPLESTORE_PASSWORD"],
        "repository": os.environ["TRIPLESTORE_TEST_DATASET"],
    }
