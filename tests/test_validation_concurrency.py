"""Query and update validation stay correct when several threads validate at once.

pyparsing probes the arity of each parse action on its first call, and the probe is not
thread-safe: two threads that make the first use of a SPARQL grammar element at the same moment
can break rdflib's shared grammar for the rest of the process. Every later parse on that path
then fails with ``Param.postParse2() missing 1 required positional argument: 'tokenList'``.

The race is per grammar element and happens only once per process, so a test inside the pytest
process proves nothing: earlier tests have already probed the grammar. Each scenario runs in a
fresh interpreter instead, 20 times, with the threads released together by a barrier.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

RUNS = 20
THREADS = 8

SELECT_WITH_FILTER = """
PREFIX ex: <http://example.org/>
SELECT ?s ?v WHERE {
    ?s ex:value ?v .
    FILTER (?v > 3 && STRSTARTS(STR(?s), "http://example.org/"))
}
"""

UPDATE = """
PREFIX ex: <http://example.org/>
INSERT DATA {
    GRAPH <http://example.org/g> { ex:s ex:p "o", 42 . }
}
"""

QUERY_SHAPES = [
    SELECT_WITH_FILTER,
    """
    PREFIX ex: <http://example.org/>
    ASK { ?s ex:p ?o . OPTIONAL { ?o ex:q ?x } FILTER (!BOUND(?x)) }
    """,
    """
    PREFIX ex: <http://example.org/>
    SELECT (COUNT(?s) AS ?n) WHERE { { ?s ex:p ?o } UNION { ?s ex:q ?o } }
    GROUP BY ?o ORDER BY DESC(?n) LIMIT 10
    """,
    """
    PREFIX ex: <http://example.org/>
    SELECT ?s WHERE { VALUES ?s { ex:a ex:b } ?s ex:p/ex:q* ?o . BIND (LANG(?o) AS ?l) }
    """,
]

UPDATE_SHAPES = [
    UPDATE,
    """
    PREFIX ex: <http://example.org/>
    DELETE DATA { GRAPH <http://example.org/g> { ex:s ex:p "o"@en } }
    """,
    """
    PREFIX ex: <http://example.org/>
    DELETE { ?s ex:p ?o } INSERT { ?s ex:q ?o } WHERE { ?s ex:p ?o FILTER (ISIRI(?o)) }
    """,
    """
    PREFIX ex: <http://example.org/>
    WITH <http://example.org/g> DELETE { ?s ex:p ?o } WHERE { ?s ex:p ?o . ?o ex:q ?x }
    """,
]

BARRIER_SCENARIO = textwrap.dedent(
    """
    import json
    import sys
    import threading

    from kapps_triplestore_interface.utils import utils

    jobs = json.loads(sys.argv[1])
    barrier = threading.Barrier(len(jobs))
    failures = []

    def validator(kind):
        return utils.validate_query if kind == "query" else utils.validate_update_query

    def run(kind, text):
        validate = validator(kind)
        barrier.wait()
        try:
            validate(text)
        except Exception as e:
            failures.append(f"{kind}: {e}")

    threads = [threading.Thread(target=run, args=job) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # A broken grammar stays broken: a later validation on the same path fails too.
    for kind, text in jobs:
        try:
            validator(kind)(text)
        except Exception as e:
            failures.append(f"afterwards, {kind}: {e}")
    print(json.dumps(failures))
    sys.exit(1 if failures else 0)
    """
)


def _run_fresh_interpreters(jobs):
    """Run the barrier scenario in RUNS fresh interpreters at once; return the failed runs."""
    argv = [sys.executable, "-c", BARRIER_SCENARIO, json.dumps(jobs)]
    procs = [
        subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(RUNS)
    ]
    failed = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        if proc.returncode != 0:
            failed.append(out.strip() or err.strip()[-500:])
    return failed


def _assert_no_run_fails(jobs):
    failed = _run_fresh_interpreters(jobs)
    assert failed == [], f"{len(failed)} of {RUNS} runs failed: {failed[0]}"


def test_concurrent_query_validation_never_breaks_the_grammar():
    _assert_no_run_fails([["query", SELECT_WITH_FILTER]] * THREADS)


def test_concurrent_update_validation_never_breaks_the_grammar():
    _assert_no_run_fails([["update", UPDATE]] * THREADS)


def test_concurrent_mixed_validation_never_breaks_the_grammar():
    _assert_no_run_fails(
        [["query", q] for q in QUERY_SHAPES] + [["update", u] for u in UPDATE_SHAPES]
    )


FORK_SCENARIO = textwrap.dedent(
    """
    import os
    import signal
    import threading

    from kapps_triplestore_interface.utils import utils

    held = threading.Event()
    release = threading.Event()

    def hold_the_lock():
        with utils._SPARQL_PARSE_LOCK:
            held.set()
            release.wait()

    holder = threading.Thread(target=hold_the_lock)
    holder.start()
    held.wait()
    pid = os.fork()
    if pid == 0:
        signal.alarm(5)  # A child stuck on an inherited locked lock dies of SIGALRM.
        utils.validate_query("SELECT * WHERE { ?s ?p ?o }")
        os._exit(0)
    _, status = os.waitpid(pid, 0)
    release.set()
    holder.join()
    raise SystemExit(0 if os.waitstatus_to_exitcode(status) == 0 else 1)
    """
)


@pytest.mark.skipif(not hasattr(os, "register_at_fork"), reason="the platform has no fork")
def test_a_forked_child_validates_while_the_parent_holds_the_lock():
    proc = subprocess.run(
        [sys.executable, "-W", "ignore::DeprecationWarning", "-c", FORK_SCENARIO],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_an_invalid_query_or_update_still_raises_with_the_same_message_and_log_line(caplog):
    from kapps_triplestore_interface.exceptions import InvalidQueryError
    from kapps_triplestore_interface.utils import utils

    with pytest.raises(InvalidQueryError, match=r"^SPAQRQL query validation failed: ") as query:
        utils.validate_query("SELECT * WHERE { ?s ?p }")
    with pytest.raises(
        InvalidQueryError, match=r"^SPAQRQL update query validation failed: "
    ) as update:
        utils.validate_update_query("INSERT DATA { <http://example.org/s> }")
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert errors == [str(query.value), str(update.value)]
