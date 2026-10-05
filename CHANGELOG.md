# Changelog

## 2.2.0 — 2026-10-05

### Added

- **`ShaclValidationError`** (`kapps_triplestore_interface/exceptions.py`, also exported from
  the package). `GraphDB.query` raises it when the store refuses an update because the data
  would violate a SHACL shape. The store then commits nothing of the update. The error's
  `.report` is the store's validation report, verbatim: the body of its answer. The report is
  not parsed.

  So a caller can tell a refusal from every other failure by its type. Catch
  `ShaclValidationError` for a refusal, and `TripleStoreInterfaceError` for any error from this
  package. `triple_add`, `triple_delete`, `triple_update`, `triples_add`, `triples_delete` and
  `triples_update` send their update through `GraphDB.query`, so they raise it too.

  The store marks its answer as a report in the media type, and the client reads only that:
  GraphDB 10.8.1 answers with HTTP 500 and `application/shacl-validation-report+n-quads`.
  Every other error status raises the same type as before. The error message keeps its form,
  `Error while querying GraphDB (<status>) - <answer>`, so code that reads the message
  keeps working.

  The client logs a refusal only at DEBUG, with the report. Up to 2.1.1 it logged it at ERROR,
  like every other error status. A refusal is an outcome that the caller expects and catches,
  so the caller decides how loud it is. Every other error status still logs at ERROR.

- **`PreconditionFailedError`** (`kapps_triplestore_interface/exceptions.py`, also exported
  from the package). A checked write raises it when the store found its precondition false.
  Nothing was written. It is a `TripleStoreInterfaceError` and a sibling of
  `GraphDbException`, not a subclass: the store answered the request successfully. It carries
  `.message`, `.triples` (the triples that the precondition named) and `.named_graph`.

- **`absent_subjects` on `triples_add` and `triples_update`.** A list of IRIs that must not yet
  be the subject of an explicit triple in the target graph. The check is one more
  `FILTER NOT EXISTS { <s> ?p ?o }` in the same update. A subject that occurs only as an
  object (a forward reference) passes. With `absent_subjects`, the write is checked also when
  `check_exist=False`. In the error, a subject appears as `(subject, None, None)`.

- **README section "What a write promises"**: the contract, the scope, the limits, and a
  measurement of two concurrent writers.

### Changed

- **A false precondition raises instead of returning `False`**
  (`triples_add`, `triples_delete`, `triples_update`, `triple_delete`, `triple_update`, with
  `check_exist=True`, the default).

  **Before:** the function sent an `ASK` and then, in a second request, the write. A false
  precondition returned `False`, and callers dropped it. The `ASK` could also be stale by the
  time the write ran.

  **Now:** the precondition is in the `WHERE` of the update itself, and the update also writes a
  receipt triple into the graph `urn:x-kapps:write-receipts`. The receipt lands only when the
  `WHERE` matched, in the same commit as the change. One `ASK` for the receipt follows. If the
  receipt is found, the function removes it and returns `True`. If the removal fails, the
  function logs a warning and still returns `True`. If no receipt is found, the function raises
  `PreconditionFailedError`. The functions keep `-> bool` and always return `True`.

  A normal return means that the store evaluated the precondition as true and committed the
  change. The store isolates only commits ("read committed"), so another writer can commit
  between the evaluation and the commit. An invariant under concurrent writers belongs in a
  SHACL shape.

- **The precondition sees only the explicit triples of the target graph.** With a named graph,
  the update uses `WITH <g>`. Without one, it uses `USING <http://rdf4j.org/schema/rdf4j#nil>`,
  which selects the explicit triples of the default graph, and writes its removals in
  `GRAPH <http://rdf4j.org/schema/rdf4j#nil> { … }`. A removal without `GRAPH` also removes the
  copies of a triple in all named graphs. Effects:

  - An old triple that is only inferred now raises. Before, the `ASK` found it, and the delete
    did nothing.
  - A checked delete without a named graph no longer removes the copies of the triple in named
    graphs. A copy in a named graph also no longer satisfies the precondition.
  - A triple that is both explicit and inferred stays visible after a delete, as before. The
    docstrings now say so.

- **`check_exist=False` is unchanged:** the same query forms as before, no receipt, and the
  return value `True`. An unchecked `triples_update` still applies only when its old triples
  match its `WHERE`.

- **Removed `SPARQLQuery.insert_exists`, `SPARQLQuery.add_insert_exists_block` and
  `SPARQLQueryType.INSERT_EXISTS`.** Their `FILTER NOT EXISTS { t1 . t2 }` means "not all of the
  triples exist", which is not the precondition of an add. Nothing called them.

### Fixed

- **`clear_graph` reported a refused clear only as a log warning**
  (`kapps_triplestore_interface/queries/rdf4j/graph_store.py`, `clear_graph`).

  **Symptom:** a clear that the store refused looked like a clear that worked. Callers that did
  not check the return value carried on over the old data. A seed that cleared the repository
  then failed later, with an error that did not name the clear. A store with SHACL validation
  refuses a clear when the remaining data would violate a shape, and it can fail with HTTP 500
  while it validates.

  **Root cause:** on any answer other than 204, `clear_graph` logged a warning and returned
  `False`. It raised nothing, unlike `GraphDB.query`.

  **Fix:** `clear_graph` raises on any answer other than 204, with the same mapping as
  `GraphDB.query`: `ShaclValidationError`, with the store's report, when the answer is a SHACL
  validation report, and `GraphDbException` otherwise. The message names the graph and the
  repository: `Failed to clear graph <iri> in repository '<id>' (<status>) - <answer>`, or
  `... the default graph ...`. Like `GraphDB.query`, it logs a refusal only at DEBUG and every
  other error answer at ERROR. On success it returns `True`, as before. It no longer returns
  `False`.

- **A read on a connection that the store closed while idle failed instead of being sent
  again** (`kapps_triplestore_interface/graph_db.py`, `GraphDB.query`).

  **Symptom:** a read raised `requests.ConnectionError: ('Connection aborted.',
  RemoteDisconnected('Remote end closed connection without response'))` when the client's
  connection had been idle for about as long as the store's idle limit. The remote GraphDB
  this was measured against closes a keep-alive connection after 5 s idle. Measured on
  2026-10-02: after an idle time of 5.0 s, 9 of 16 reads failed; after 4.5 s and after 6.0 s,
  none of 16 failed. With the fix, 16 of 16 reads succeeded after 5.0 s idle, 9 of them on
  the second send.

  **Root cause:** the client keeps one session per thread, so its connections are reused
  across calls. When the next request leaves on a pooled connection just as the store closes
  it, the store answers nothing. Nothing in the client sent the request again.

  **Fix:** when a read (`update=False`) gets no answer because the store closed the
  connection, `GraphDB.query` sends it once more, on a fresh connection. A second failure
  raises `requests.ConnectionError` as before. An update (`update=True`) is never sent again,
  because the store may have applied it, and a second one could apply it twice. It raises as
  before. Every function that reads through `GraphDB.query`, for example `triples_get` and
  `triple_exists`, gets the retry as well.

- **Joining two groups of blank-node triples raised `TypeError`**
  (`kapps_triplestore_interface/utils/utils.py`, `group_triples_by_bnode`).

  **Symptom:** `any_triple_exists`, and therefore `triples_add` with its default
  `check_exist=True`, raised
  `TypeError: unsupported operand type(s) for |=: 'list' and 'list'` on an OWL list or
  intersection. In such a structure, one triple links two blank nodes that are already in
  different groups, for example an `rdf:first` cell and the restriction that it points at.

  **Root cause:** the function merged the two groups with `|=` on two lists. With `|=` made
  valid, the merge would still be incomplete: only the triple's own blank nodes pointed at the
  merged group, and the other members of the absorbed group kept the old one.

  **Fix:** the function keeps each group as its set of blank nodes and its triples. A triple
  that touches several groups joins all of them into the first, with all their members. Groups
  keep the order of their first triple. New tests cover two groups that one triple joins.

- **A literal with a datatype outside the type map made its whole result set unreadable**
  (`kapps_triplestore_interface/utils/utils.py`, `from_xsd_literal`).

  **Symptom:** `GraphDB.query(..., convert_bindings=True)` raised `KeyError` when one literal
  in the result had such a datatype. `triples_get` failed the same way. Custom datatypes
  failed, for example GeoSPARQL's `wktLiteral`. So did XSD types that the map does not
  cover, for example `xsd:dateTimeStamp` and `xsd:gMonth`. A write of the same literal
  worked.

  **Root cause:** `from_xsd_literal` looked up the datatype in `XSDToPythonMapper` with a
  bare subscript. RDF allows any IRI as a datatype, and the map has no fallback.

  **Fix:** a datatype without a converter now gives back an `rdflib.Literal` that keeps the
  datatype. rdflib's own `Literal.toPython()` does the same. The `Literal` is a `str`, and
  `str(value)` gives its lexical form. A write with the value stores the same typed literal
  again. A plain `str` would lose the datatype, and `triples_add` would read it as an IRI.
  Datatypes in the map convert as before.

  Reported, with a first fix, by Jingcheng Wu in a pull request on the public repository.

## 2.1.1 — 2026-09-17

### Fixed

- **Installing the package emitted a `SyntaxWarning`**
  (`kapps_triplestore_interface/utils/iri.py`, `IRI`'s class docstring).

  **Symptom:** the first compile of an installed checkout — so once per install, before
  the user has written a line of their own code — printed

  ```
  site-packages/kapps_triplestore_interface/utils/iri.py:13: SyntaxWarning: invalid
  escape sequence '\`'
  ```

  **Root cause:** the docstring is not raw and lists `` - Trailing `#`, `\` or `:` ``, so
  `` \` `` is read as an escape sequence, and there is no such escape. Python has warned
  about this since 3.6. The defect predates the fork and the rename: `JaFeKl/graph_db_interface`
  carries the same line, in `utils/iri.py`.

  **Fix:** the docstring is raw (`r"""`). Raw rather than a doubled backslash, because the
  text is full of backticks and the next backslash added to it would repeat the defect.
  The docstring's rendered text is unchanged — an invalid escape was already kept
  literally.

  A new `tests/test_compile_warnings.py` compiles every source file in the package with
  `SyntaxWarning` raised as an error, so the next one fails CI instead of reaching PyPI.
  It compiles rather than imports, because a warm `__pycache__` hides a compile-time
  warning from an import.

## 2.1.0 — 2026-08-12

First public release, and the first under this name.

### Lineage

Forked from [`graph-db-interface`](https://github.com/JaFeKl/graph_db_interface) by Jan-Felix Klein, MIT. That project's last
release is 2.0.1; this one is cut from the `dev_semantic_middleware` branch of
[`SAWeindel/graph_db_interface`](https://github.com/SAWeindel/graph_db_interface), which carries five commits that are
in no released `graph-db-interface`:

- `34dac9e` — the IRI validator rejected any URL carrying a port
- `65157c5` — `triples_update` generalised to atomic add / remove / replace
- `e659da1` — blank-node identity kept across `triples_update`
- `c90c940` — a per-thread HTTP session, so requests stop re-handshaking
- `da08373` — tests pinning the asymmetric `triples_update` contract

The import package and the distribution both rename: `graph_db_interface` → `kapps_triplestore_interface` and
`graph-db-interface` → `kapps-triplestore-interface`. The exception base `TripleStoreInterfaceError` renames with them.
`GraphDB`, `GraphDBCredentials`, `use_gdb_token` and the word *repository* do **not** — a GDB
token is a GraphDB-only mechanism and *repository* is RDF4J's own word, so a backend-neutral
spelling of either would hide a vendor detail rather than abstract it.

No git history is carried. This repository takes one commit per release, so the credit that
history would have carried lives in `LICENSE`, `pyproject.toml`, `README.md` and here instead.
Jan-Felix Klein's 2025 copyright notice is retained in `LICENSE` as the MIT licence requires.

**Why a first release is numbered 2.1.0**: it is the same mature library renamed, so `2.x`
tells the truth about it where `0.x` would falsely say *I may break you*. Minor rather than
patch because `65157c5` adds a feature. Not 3.0.0, because semver's breaking-change rule
governs upgrades within one distribution name and there is no upgrade path between these two —
a consumer edits their manifest, and that edit is the migration signal.

### Changed

- **`triples_update` now performs a general atomic update, not only equal-length
  replacement** (`kapps_triplestore_interface/queries/triple_multi.py`).

  Previously `triples_update` raised `InvalidInputError` unless `old_triples` and
  `new_triples` had the same length, restricting it to 1:1 value replacement. The
  method already builds a single `DELETE ... INSERT ... WHERE` SPARQL transaction,
  which handles pure additions, pure removals, and unequal-size replacements
  equally well, so the length restriction was removed. The existence pre-check is
  now skipped when `old_triples` is empty (a pure insert has nothing to check).

  This atomicity is required for constraint (SHACL) correctness: replacing a
  cardinality-constrained property — e.g. a possession handover under a "possessed
  by exactly one resource" shape — must apply the removal and the insertion in one
  transaction so the intermediate (property-absent) state is never validated.

  Enables `kapps_ogm.OGM.commit` to add/remove/replace properties through a single
  atomic transaction. Requested by the `kapps_semantic_middleware` project.

### Fixed

- **Every request opened a new TCP connection and re-ran the TLS handshake**
  (`kapps_triplestore_interface/graph_db.py`).

  **Symptom:** every call through the client — query, update, graph import, repository
  listing — cost far more than the work it asked the server to do. Against a remote HTTPS
  endpoint a trivial `ASK { ?s ?p ?o }` measured
  ~17 ms, of which only ~4 ms was the request itself. The cost was invisible per call and
  compounded with volume: a single `kapps_semantic_middleware` integration test issues 129
  requests, so it paid ~1.7 s in handshakes alone.

  **Cause:** `_make_request` dispatched through the module-level `requests` helpers,
  `getattr(requests, method)(...)`. Those are documented convenience wrappers that
  construct a `requests.Session`, use it for exactly one request, and close it. Closing the
  session discards its `urllib3` connection pool, so no connection was ever reused and each
  call paid a fresh TCP connect plus a full TLS handshake. Confirmed by counting
  `urllib3` connection creations: three sequential queries opened three
  `HTTPSConnectionPool` connections.

  **Fix:** the client now holds a persistent `requests.Session` **per thread** and issues
  every request through it, so the connection pool survives across calls. Per thread rather
  than one shared session because a `requests.Session` mutates its cookie jar on every
  response and is not thread-safe — and one client is commonly driven from several threads
  at once, e.g. a web framework serving requests while the embedding code queries. urllib3's
  connection pools are thread-safe; the session wrapping them is not. Each thread pays one
  handshake and then reuses its own pool. Added `GraphDB.close()`, which releases the pools
  held for every thread that used the client. No change to any method signature or response
  handling.

  **Measured effect:** per-request cost against the remote endpoint dropped from ~17 ms to
  ~4 ms. The `kapps_semantic_middleware` suite (146 tests, live GraphDB) went from 158 s to
  60 s — a 2.65× speed-up with no test changes. Regression test:
  `tests/test_connection_reuse.py`.

- **`triples_update` replaced a retained blank node instead of updating it**
  (`kapps_triplestore_interface/queries/triple_multi.py`).

  **Symptom:** updating one property of an existing blank node was impossible. The node
  was unlinked and a *different* node took its place, so every triple attached to the
  original that the caller had not listed in `old_triples` became unreachable — silently,
  with the call reporting success.

  **Cause:** the DELETE and INSERT patterns were rendered from two separate blank-node →
  variable maps (`old_bn_var_map` / `new_bn_var_map`). A `BNode` passed on both sides —
  the caller's way of saying "same node, different property value" — therefore became
  `?oldbn1` in the DELETE and `?newbn1` in the INSERT, and every new-side variable was
  bound by `BIND(BNODE() AS ?newbnN)`, which mints a fresh store node. Captured query
  before the fix, for a node whose only change is its value:

  ```sparql
  DELETE { <Belt1> :hasValue ?oldbn1 . ?oldbn1 :hasValue 12.1 }
  INSERT { <Belt1> :hasValue ?newbn1 . ?newbn1 :hasValue 1.4 }
  WHERE  { <Belt1> :hasValue ?oldbn1 . ?oldbn1 :hasValue 12.1 . BIND(BNODE() AS ?newbn1) }
  ```

  **Fix:** one shared map across both pattern sets, so a blank node present on both sides
  renders as a single variable already bound by the WHERE clause. `BIND(BNODE() AS ?v)` is
  now emitted only for blank nodes exclusive to `new_triples`. Behaviour for pure
  additions, pure removals, unequal-length replacements and the IRI-only path is unchanged,
  as is the single-transaction atomicity the SHACL note above depends on.

  **Tests:** `tests/test_triple_update_query.py` asserts on the generated SPARQL and needs
  no live repository, unlike the existing update tests. Verified red before the change and
  green after: the two blank-node-identity tests fail on the previous implementation, the
  two control tests pass on both.

  Found while designing anonymous-node identity in `kapps_ogm` (see
  https://github.com/JaFeKl/graph_db_interface/issues/6); a correctness fix for this library
  independently of that work. Reported by the `kapps_semantic_middleware` project.

- **`IRI` rejected any URL containing a port** (`kapps_triplestore_interface/utils/iri.py`,
  `IRI._sanitize`).

  **Symptom:** constructing an `IRI` from a perfectly valid `http`/`https` URL that
  includes a port raised `InvalidIRIError: ':' outside of supported schemes`:

  ```python
  IRI("http://127.0.0.1:8991")                      # raised
  IRI("http://host:8991/workflows/x/execute")       # raised
  ```

  This also broke reads: `triples_get` / `query(convert_bindings=True)` convert an
  `xsd:anyURI` literal to an `IRI` via `from_xsd_literal`, so any stored
  `xsd:anyURI` value that was a ported URL made the read itself throw.

  **Root cause:** for a full IRI beginning with a known scheme, the validator
  rejected the whole string when `raw.count(":") > 1`. A scheme contributes one
  colon (`http://`) and an authority port contributes a second (`:8991`), so every
  ported URL tripped the check. The check's real intent is to catch a `:` used
  where a `#` was meant (e.g. `http://…/owl:Class`).

  **Fix:** after confirming the scheme, strip the scheme, split off the authority
  (up to the first `/`, `#`, or `?`), remove a trailing `:<digits>` port from the
  authority, and only then reject if a stray `:` remains in the authority or the
  remainder. Ports are now accepted; the previously-rejected malformed forms
  (`http://www.w3.org/2002/07:owl#`, `http://www.w3.org/2002/07/owl:Class`, etc.)
  are still rejected. All existing `tests/test_iri.py` cases continue to pass.

  **Reported/fixed by:** the `kapps_semantic_middleware` project, whose Service
  ontology stores middleware endpoint URLs (`svc:address`, `svc:endpoint`) — always
  `host:port` values — as `xsd:anyURI`, and which hit this on the first round-trip
  of a registered endpoint. That project's dependency-and-bugfix policy has genuine
  correctness bugs in a dependency fixed in the dependency, with a detailed changelog
  entry — this is that entry.
