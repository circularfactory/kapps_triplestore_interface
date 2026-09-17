"""Shared pytest fixtures.

This is an integration suite. 84 of its 107 tests drive a real GraphDB, because that is the
thing this library exists to wrap and a mock of it would only assert that the mock was called.
The development repository's CI provisions a disposable GraphDB for them, so all 107 run there.
A checkout without a triple store runs the 23 tests that need none and skips the rest, which is
a report of what was not run rather than a claim that it passed.

The four ``GRAPHDB_*`` variables below select the store. The suite wipes what it connects to,
so they must not point at anything of value; CI points them at a repository it created empty
inside the job and destroys with the job.

That last sentence used to be the whole protection: an instruction, obeyed by habit. `db` now
refuses any target it cannot tell is disposable. See ``is_disposable_target`` below for what
disposable means and for the one variable that overrides it.
"""

import os
from urllib.parse import urlsplit

import pytest
from kapps_triplestore_interface import GraphDB, GraphDBCredentials

REQUIRED_ENV = (
    "GRAPHDB_URL",
    "GRAPHDB_USERNAME",
    "GRAPHDB_PASSWORD",
    "GRAPHDB_TEST_REPOSITORY",
)

# A fixture that destroys data must be **told** its target is disposable rather than infer the
# permission from a URL being set. `GRAPHDB_TEST_REPOSITORY` names the intent but asserts
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
# - **`GRAPHDB_ALLOW_DESTRUCTIVE=1` is set**, which is a person saying so in as many words.
#
# The opt-in is deliberately not named after any of the three variables on group
# `circular_factory` (`GRAPHDB_USER`, `GRAPHDB_PASSWORD`, `GITHUB_CIRCULAR_FACTORY_TOKEN`). A
# protected group variable outranks one declared in `.gitlab-ci.yml` and arrives only on
# protected refs, which is exactly how a job passes every merge request and then fails the
# moment it merges.
#
# `kapps_ogm/tests/conftest.py` carries the same guard, deliberately duplicated: there is no
# shared test package between these repositories, and a pointer cannot be imported.
ALLOW_DESTRUCTIVE_ENV = "GRAPHDB_ALLOW_DESTRUCTIVE"

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
    names it. That transitive case is the one that gets missed by hand: it is what let the
    sibling `kapps_ogm` describe a whole directory as mock-only while 28 of its tests reached a
    live store through an intermediate fixture.

    ``-m "not live"`` then selects the tier that runs anywhere. Nothing in CI passes that flag:
    CI has a triple store and runs the whole suite.
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

    url = os.getenv("GRAPHDB_URL")
    if not is_disposable_target(url) and os.getenv(ALLOW_DESTRUCTIVE_ENV) != "1":
        pytest.fail(
            f"refusing to clear graphs in repository "
            f"{os.getenv('GRAPHDB_TEST_REPOSITORY')!r} on {url!r}.\n"
            "This fixture wipes the default context and two named graphs at session start, and "
            "that host is neither loopback nor a container alias, so nothing here can tell that "
            "it is disposable.\n"
            "Point GRAPHDB_URL at a local GraphDB or a service alias, or set "
            f"{ALLOW_DESTRUCTIVE_ENV}=1 to state that the target is disposable.",
            pytrace=False,
        )

    credentials = GraphDBCredentials(
        base_url=os.getenv("GRAPHDB_URL"),
        username=os.getenv("GRAPHDB_USERNAME"),
        password=os.getenv("GRAPHDB_PASSWORD"),
        repository=os.getenv("GRAPHDB_TEST_REPOSITORY"),
    )

    db = GraphDB(credentials=credentials)

    for graph in [
        None,
        "http://example.org/named_graph",
        "http://example.org/local_named_graph",
    ]:
        db.clear_graph(graph)

    return db
