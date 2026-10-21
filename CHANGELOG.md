# Changelog

## 2.2.2 — 2026-10-20

### Added

- **`validate(shapes, content_type)` joins the store contract and the GraphDB adapter**
  (`TripleStore` and `GraphDB`, with the store registries). It validates the whole dataset
  against a shapes document through the store's validation endpoint and returns the store's
  report verbatim, Turtle on GraphDB. A violation is part of the report, not an error. The call
  changes neither the dataset nor the shapes that the store validates writes against. A 404
  raises `InvalidDatasetError`, a 401 `AuthenticationError` and a 403 `TripleStoreAccessError`;
  a store without whole-dataset validation raises `TripleStoreNotSupportedError`, as the other
  registry operations do.

### Changed

- **The test suite builds its store with `connect()` and reads only the `TRIPLESTORE_*`
  variables** (tests only). The dataset comes from `TRIPLESTORE_TEST_DATASET`, the dataset
  without SHACL validation from `TRIPLESTORE_TEST_DATASET_WITHOUT_SHACL`, and the override of
  the guard against a store that is not disposable is `TRIPLESTORE_ALLOW_DESTRUCTIVE`. The
  tests of the deprecated `GraphDBCredentials` build them from the same variables themselves.
  A live test records what the store does with a SHACL-SPARQL constraint: a class-targeted
  constraint refuses a write at commit only when the write creates the focus node together
  with the violation, and whole-dataset validation finds the violations that a later change
  admits.

### Fixed

- **`iri_exists` finds an IRI that holds any of the asked positions**
  (`kapps_triplestore_interface/queries/ontology_helpers.py`). With several of `as_sub`,
  `as_pred` and `as_obj`, the read put the patterns side by side, which SPARQL joins: the IRI
  had to hold every chosen position at once. An instance IRI is never a predicate, so a read
  for all three positions always answered `False`, against the docstring ("subject, predicate,
  or object"). The positions are now alternatives (`{ <I> ?p ?o } UNION { ?s <I> ?o } UNION
  { ?s ?p <I> }`, in the one graph block, so the named graph and the scope options apply to
  all). A read with one position sends the same query as before; a read without a position is
  still refused. Two effects follow. An OGM paired with this interface needs a matching
  change in its validator (a `kapps_ogm` release that adopts this interface): its validator asks all three positions and
  then tests subclass-of. Before this fix that read answered `False` for every instance; now
  it finds the instance, so an OGM without the change would refuse every existing instance.
  `new_iri` keeps its read of all three positions, which is now correct: it retries an IRI
  that is already in use.

- **Stale docstrings and metadata are corrected.** `triple_add` lost a failure branch that
  could not be reached; it returns `True` or raises, and its docstring says so. The docstring of
  `query` gives the real default of `convert_bindings`, `False`. The `live` marker text and the
  test conftest no longer quote test counts or name the private CI group. Both XSD maps say why
  they differ: `XSDToPythonTypes` names the Python type of a value, so `xsd:anyURI` stays an
  `IRI` there, and `XSDToPythonMapper` converts the lexical form and keeps it a string.

### Removed

- **`KafkaManager` goes without a deprecated alias, and so do the `kafka` and `kafka-inst`
  IRI prefixes.** The Kafka connector manager (`GraphDB.kafka_manager`, the
  `kapps_triplestore_interface.kafka` package, the export and its reference page) is removed.
  No alias ships because every method of the class raised on its first use, so no caller can
  depend on it, and a vendor-specific component has no place above the store contract. The IRI
  prefix registry now names no vendor namespace.

## 2.2.1 — 2026-10-16

### Added

- **`connect(endpoint, auth)` gives a caller a working, authenticated store**
  (`kapps_triplestore_interface/connection.py`, also exported from the package). It builds the
  GraphDB adapter, makes the auth provider log in now, and sends one probe, `ASK {}` on the
  dataset. It returns the store, or raises: `TripleStoreUnavailableError` when the store
  cannot be reached, `AuthenticationError` on a 401, `TripleStoreAccessError` on a 403,
  `InvalidDatasetError` when the dataset does not exist, and `TripleStoreResponseError` on
  any other error answer.

- **The store contract** (`kapps_triplestore_interface/store.py`, also exported from the
  package).

  - **`TripleStore`**, a `Protocol`: the operations that code above the interface calls on a
    store, and no other. Its docstring lists them. `GraphDB` implements it without inheriting
    from it, and so does a test double.
  - **`TripleStoreEndpoint(url, dataset)`**: where a store is. It holds no secret.
    `TripleStoreEndpoint.from_env(dataset=None)` reads `TRIPLESTORE_URL` and
    `TRIPLESTORE_DATASET`.

- **The store registries: a dataset's prefixes and its SHACL shapes** (`TripleStore` and
  `GraphDB`). SPARQL does not cover them, so the contract has four operations for them:
  `prefixes_get()` returns each prefix with its namespace IRI as a `dict`, `prefix_set(prefix,
  iri)` and `prefix_delete(prefix)` change one prefix, and `shapes_set(data, content_type)`
  replaces the SHACL shapes that the store validates against; an empty document removes every
  shape. `""` is the empty prefix. A store that has no such registry raises
  `TripleStoreNotSupportedError`, never a silent no-op: an adapter that inherits `TripleStore`
  without a registry raises it from the contract's own operations. The GraphDB adapter uses
  the dataset's namespaces and RDF4J's shapes graph. Before it writes the shapes, it reads the
  repository's configuration, and on a dataset without SHACL validation, or one whose
  configuration does not say, `shapes_set` raises `TripleStoreNotSupportedError` and writes
  nothing. The shapes are replaced in one request, which the store applies whole or not at
  all: if the store refuses it, because the data violates the new shapes,
  `ShaclValidationError` raises and the old shapes stay.

- **Auth providers** (`kapps_triplestore_interface/auth.py`, also exported from the package).
  `auth` in `connect()` and in `GraphDB` is typed `BasicAuth | GDBTokenAuth`; there is no
  public type of a provider. `BasicAuth(username, password)` sends HTTP Basic
  authentication. `GDBTokenAuth(username, password)` logs in for a GDB token on first use,
  logs in again when the token is 29 days old (GraphDB's default validity is 30 days), and
  once after the store answers 401. Each has `from_env()`, which reads `TRIPLESTORE_USERNAME`
  and `TRIPLESTORE_PASSWORD`. A provider's `repr` never shows the password.

- **`GraphDB` builds from an endpoint and an auth provider, and sends no request then**
  (`GraphDB(endpoint=..., auth=...)`, keyword-only). The provider logs in at the first
  request. Built from `credentials`, the client logs in and checks the repository when it is
  built, as before.

- **Error types that name their action** (`kapps_triplestore_interface/exceptions.py`, also
  exported from the package). Each type tells the caller one action: Repair, Retry, Refresh,
  Refused or Fix the call. Its docstring names it, and the README's section "When a call fails"
  lists them.

  - **`TripleStoreResponseError`**: the store answered with an error status. `status` is the
    store's HTTP status, and the message holds the store's answer unchanged. It replaces
    `GraphDbException`. It constructs with a message alone, as `GraphDbException` did; `status`
    is then `None`.
  - **`TripleStoreUnavailableError`**: the store cannot be reached, it did not answer in time,
    or the connection dropped. It is chained to the error of the HTTP client. Its docstring
    states why a caller's retry of a write is safe.
  - **`TripleStoreAccessError`**: the store answered 403. A subtype of
    `TripleStoreResponseError`.
  - **`TripleStoreNotSupportedError`**: the store, or the repository, cannot do the operation.
    The store registries raise it.

  `AuthenticationError` and `ShaclValidationError` are now subtypes of
  `TripleStoreResponseError`, and they carry `status` too. So `except GraphDbException` still
  catches each of them.

### Changed

- **A request that the store answers with 401 is sent once more after a new login**
  (`GraphDB._make_request`, so every operation, also of a client built from `credentials`
  with a GDB token). The provider logs in again once, and the request is sent once more with
  the new token; a second 401 raises `AuthenticationError`. This is safe for a write: a store
  that answers 401 has not applied it. Up to 2.2.0 the client never logged in again, so every
  request failed with a 401 once the token expired or the store restarted.
  With Basic authentication a 401 still raises at once.

- **An error answer of the store raises the type of its status**
  (`GraphDB.query`, `graph_clear`, which was `clear_graph`, the login).
  A 401 raises `AuthenticationError`, a 403 `TripleStoreAccessError`, a SHACL validation report
  `ShaclValidationError` as before, and any other error status `TripleStoreResponseError`. Each
  carries the status. Up to 2.2.0, a 401 or a 403 of a query or a clear raised the general type.
  The messages keep their form.

- **The login reports the store's answer.** A refused login raises the type of its status, with
  the message `Failed to obtain a GDB token (<status>) - <answer>`. Up to 2.2.0 every refused
  login raised `AuthenticationError` with a fixed message that held neither the status nor the
  answer. A login that the store answers with 401 still raises `AuthenticationError`.

- **A request that gets no answer raises `TripleStoreUnavailableError`**
  (`GraphDB._make_request`, so every operation). Up to 2.2.0 the error of the HTTP client
  crossed unchanged: `requests.ConnectionError`, `requests.ReadTimeout` and the others of their
  families. The interface's error is chained to it: `__cause__` is that error, and the message
  names the request and quotes it. A read whose pooled connection the store closed while idle
  is still sent again once. A write is still never sent again. An error of the HTTP client that
  is not a failure of the transport, for example a URL without a scheme, is raised unchanged.

- **Listing the repositories and fetching a graph raise on an error answer**
  (`GraphDB.datasets_get` and `graph_get`, which were `get_list_of_repositories` and
  `fetch_statements`). Up to 2.2.0 they logged a warning and
  returned `None`. They now log at ERROR and raise the type of the status, with the message
  `Failed to list repositories (<status>) - <answer>` or
  `Failed to fetch <graph> in repository '<repository>' (<status>) - <answer>`. A client that is
  built while the store refuses the list raises that error. Up to 2.2.0 it raised a `TypeError`.

- **The existence checks have no branch for a missing answer**
  (`triple_exists`, `any_triple_exists`, `all_triple_exists`, `iri_exists`). `GraphDB.query`
  raises the store's error before them, so the branch never ran. A failing store raises the
  store's error, never `InvalidInputError`, and never reads as `False`.

### Deprecated

- **`GRAPHDB_URL`, `GRAPHDB_REPOSITORY`, `GRAPHDB_USERNAME` and `GRAPHDB_PASSWORD` are the
  deprecated fallback of the `TRIPLESTORE_*` variables.** The `from_env()` methods of the
  endpoint and of the auth providers read a `GRAPHDB_*` variable when its `TRIPLESTORE_*`
  variable is not set, and emit one `DeprecationWarning` that names the variable which
  replaces it. `GraphDB.from_env()` reads the `GRAPHDB_*` variables as before, without a
  warning. `GraphDBCredentials.from_env()` reads them as before too; only the use of the
  deprecated name `GraphDBCredentials` warns, as the next entry says.

- **The public names follow one convention and name no vendor, and the old names are
  deprecated aliases.** The names are those of the KAPPS family's decision record *The triple
  store border*: the noun first and the verb second, the Graph Store verbs of the SPARQL 1.1
  Graph Store HTTP Protocol, and *dataset* for the unit of a store, which GraphDB calls a
  repository. Each old name still works. Each use of it emits one `DeprecationWarning` that
  names its successor, at the line that uses it. A later major release removes them.

  | Old | New |
  |---|---|
  | `GraphDB.fetch_statements` | `GraphDB.graph_get` |
  | `GraphDB.import_statements` | `GraphDB.graph_add` |
  | `GraphDB.clear_graph` | `GraphDB.graph_clear` |
  | `GraphDB.get_list_of_named_graphs` | `GraphDB.graphs_get` |
  | `GraphDB.get_list_of_repositories` | `GraphDB.datasets_get` |
  | the store's `repository` attribute, read or set | the store's `dataset` attribute |
  | `GraphDBCredentials` | a `TripleStoreEndpoint` and an auth provider, `GDBTokenAuth` or `BasicAuth` |
  | the `use_gdb_token` flag of `GraphDB` | the auth provider: `GDBTokenAuth`, or `BasicAuth` for `use_gdb_token=False` |
  | `InvalidRepositoryError` | `InvalidDatasetError` |

  - **The methods and the attribute.** A new name takes the same parameters and does what its
    old name did; the old name calls it. So `graph_add` and `import_statements` raise alike
    when the store does not accept an import (see *Fixed*). Setting `dataset` checks that the
    store has the dataset, as setting `repository` did. The contract type `TripleStore`
    declares the new names only.
  - **`GraphDBCredentials`.** Each use of the name warns: an import of it from the package or
    from `kapps_triplestore_interface.utils.graph_db_credentials`, or a read of it as an
    attribute. The class is the same, so its fields, `from_env()` and `GraphDB(credentials=...)`
    keep working, and a client built from it builds the endpoint and the auth provider from it,
    without a second warning. The package's `__all__` still names it, so `import *` imports it
    and warns once.
  - **`use_gdb_token`.** Each call of `GraphDB` that gives the flag warns, by keyword or by
    position. Without it, a client built from credentials uses the GDB token, as before.
  - **`InvalidRepositoryError`.** It is the same class as `InvalidDatasetError`, so `except
    InvalidRepositoryError` catches the new name's errors. Each use of the old name warns, as
    the use of `GraphDbException` does.

- **`GraphDbException` is a deprecated alias of `TripleStoreResponseError`.** It is the same
  class, so `except GraphDbException`, a subclass of it and `GraphDbException(message)` keep
  working. Each use of the old name emits one `DeprecationWarning` that names
  `TripleStoreResponseError`. A later major release removes it.

### Fixed

- **Query and update validation stay correct when several threads validate at once**
  (`kapps_triplestore_interface/utils/utils.py`, `validate_query` and `validate_update_query`).
  Two threads that made the first use of a SPARQL grammar element at the same moment could
  break rdflib's shared grammar for the rest of the process, and every later validation on
  that path failed with `InvalidQueryError: ... Param.postParse2() missing 1 required
  positional argument: 'tokenList'`. pyparsing's first-call probe of each parse action is not
  thread-safe, and no released rdflib or pyparsing fixes it. Every rdflib SPARQL parse the
  interface makes now runs behind one process-wide lock; a forked child gets a free lock. A
  single thread sees no change.

- **A query no longer parses and formats its answer for a DEBUG line that is off**
  (`kapps_triplestore_interface/graph_db.py`, `query`). The DEBUG line was an f-string that
  called the response's JSON parser and formatted the whole answer, so Python did it whether
  DEBUG was on or not: every answer was parsed twice and formatted, about 1.2 s per 157 MB
  read. The answer is now parsed once, and the line is formatted only when the logger writes
  it. With DEBUG on, the line is the same as before.

- **`IRI` accepts `urn:` IRIs, so a leftover receipt no longer breaks converted reads,
  `graphs_get` and the clear of the receipt graph**
  (`kapps_triplestore_interface/utils/iri.py`). A checked write names its receipt
  `urn:uuid:<uuid4>`, its predicate `urn:x-kapps:appliedAt` and its graph
  `urn:x-kapps:write-receipts`. `IRI` refused all three ("multiple ':' separators"), so a
  receipt that stayed behind (a process stopped, or the delete of the receipt failed) made each
  read with `convert_bindings=True` that reached it raise, made `graphs_get` raise, and made
  `graph_clear` of the receipt graph raise before it sent a request. `IRI` now accepts the form
  `urn:<NID>:<NSS>` (RFC 8141 syntax): a lower-case `urn:`, a NID of 2 to 32 letters, digits or
  hyphens that neither starts nor ends with a hyphen, a non-empty NSS that can contain `:`, and
  at most one `#`. The string is kept as it is. Malformed `urn:` input still raises
  `InvalidIRIError`; so do other schemes such as `mailto:`, and an upper-case `URN:`. The
  messages of the checks that count `:` are unchanged. `.short` still raises `ValueError` for
  an IRI without `#`, as for http(s) IRIs.

- **`import_statements` raises when the store does not accept the import**
  (`kapps_triplestore_interface/queries/rdf4j/graph_store.py`). It returned `False` on a
  refused write, and the store's answer reached only a log warning, so a SHACL repository's
  refusal went unnoticed. Now any answer but 204 raises, as `clear_graph()` does:
  `ShaclValidationError` with the store's report, `AuthenticationError` on a 401 (also after
  the one new login), `TripleStoreAccessError` on a 403, and `TripleStoreResponseError` with
  the status and the body on any other status. A 204 still returns `True`. POST and PUT, for a
  named graph and for the default graph, behave alike. A caller that read the return value
  as a success flag now catches the exception instead. The import's new name is `graph_add`
  (see *Deprecated*); both names raise.

- **`to_literal` replaced the datatype of an `rdflib.Literal` with `xsd:string`**
  (`kapps_triplestore_interface/utils/utils.py`, `to_literal`).

  **Symptom:** `to_literal(Literal("http://h:1/", datatype=XSD.anyURI))` gave
  `"http://h:1/"^^xsd:string`. A writer that passes each literal value through `to_literal`,
  as an object-graph mapper does, stored a typed literal as `xsd:string`. So a URL-valued
  property, for example the address of a service, could not be stored as the `xsd:anyURI`
  that its ontology declares.

  **Root cause:** a `Literal` is also a `str`. Without a `datatype` argument, `to_literal` gave
  every `str` the datatype `xsd:string`, and rdflib lets that argument replace the datatype of
  a `Literal`.

  **Fix:** without a `datatype` argument, a `Literal` keeps its own datatype. A `datatype`
  argument still replaces it. A plain `str`, and a `Literal` without a datatype, still become
  `xsd:string`.

- **An `xsd:anyURI` value was read as an `IRI`, so it could not be updated or removed**
  (`kapps_triplestore_interface/utils/xsd_typemap.py`, `XSDToPythonMapper`).

  **Symptom:** `triples_get` and `GraphDB.query(..., convert_bindings=True)` gave an
  `xsd:anyURI` literal back as an `IRI`, and the `IRI` dropped a trailing slash:
  `"http://h:1/"` was read as `IRI('http://h:1')`. A write that named the value as read named a
  term that the store does not hold. A checked update or delete of the value raised
  `PreconditionFailedError`, and an unchecked one changed nothing. A value with a scheme other
  than `http` or `https`, for example `mqtt://broker:1883`, made the read raise
  `InvalidIRIError`.

  **Root cause:** `XSDToPythonMapper` converted `xsd:anyURI` with `IRI`. `IRI` normalises its
  input for use as a node: it removes a trailing `/`, `#` or `:`, and it accepts only `http`
  and `https` IRIs and registered prefixes. The lexical form of a literal must stay as stored.

  **Fix:** `xsd:anyURI` has no converter any more; the map gives `None` for it, as rdflib's own
  map does. The value reads back as an `rdflib.Literal` with the datatype `xsd:anyURI` and the
  lexical form as stored, like every other datatype without a converter. `to_literal` and the
  write functions write that `Literal` as the same typed literal, so a value that was read can
  be updated and removed.

  **What changes for a caller:** a read of an `xsd:anyURI` literal returns a `Literal`, not an
  `IRI`. A `Literal` is a `str`, and `str(value)` is the value as stored. Code that used the
  value as an `IRI`, for example in a query pattern, converts it explicitly with
  `IRI(str(value))`. An IRI that is stored as a node, not as a literal, still reads as an `IRI`.
  To write a URL-valued literal, pass `Literal(value, datatype=XSD.anyURI)`: an `IRI` or a
  plain `str` in the object position is written as a node.

  **Tests:** the new offline tests in `tests/test_anyuri_round_trip.py` use an in-memory
  rdflib dataset behind the client's HTTP layer. They write, read, re-address and remove
  `xsd:anyURI` values, with a trailing slash and with the scheme `mqtt`, and they replace a
  value that is stored as `xsd:string` with an `xsd:anyURI` value.

- **`get_list_of_repositories()` and `fetch_statements()` failed after an idle close instead of
  being sent again**
  (`kapps_triplestore_interface/graph_db.py`, `GraphDB._make_request`;
  `kapps_triplestore_interface/queries/rdf4j/graph_store.py`, `fetch_statements`).

  **Symptom:** when the store closed a keep-alive connection while it sat idle, the next
  `get_list_of_repositories()` or `fetch_statements()` call on it raised `requests.ConnectionError`
  with `RemoteDisconnected`. `GraphDB.query()` already sent its read once more in that case.

  **Fix:** both reads now send once more on a fresh connection, under the same rule as
  `query()`: one more send, only when the store closed the connection without an answer. Any
  other failure is raised with no second send, and so is a second idle close. The retry is one
  flag, `retry_after_idle_close`, on `GraphDB._make_request`; `query()` uses it for a read
  too. A write is never sent again. An idle close that arrives over TLS as an end-of-file error
  is still not retried.

  **Tests:** the new offline tests in `tests/test_idle_connection_retry.py` use the local
  keep-alive server that closes the idle connection before each read. They cover both reads,
  a second idle close, and a failure that is not an idle close.

- **`InvalidRepositoryError` printed an empty list when the server has no repositories**: it now says that the server has no repositories and names the server (`GraphDB._validate_repository`); a name missing from a non-empty list keeps its message.

- **The wheel ships the `py.typed` marker (PEP 561)**, so that a type checker such as mypy reads the package's own annotations instead of reporting an untyped import for every import of `kapps_triplestore_interface`.

- **The package metadata listed Jan-Felix Klein with a misspelt e-mail address**: the `authors` entry in `pyproject.toml` now carries his working address, `jfklein@kth.se`. Releases already published keep the old address.

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
