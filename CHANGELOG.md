# Changelog

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
  `JaFeKl/graph_db_interface#6`); a correctness fix for this library independently of that
  work. Reported by the `kapps_semantic_middleware` project.

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
