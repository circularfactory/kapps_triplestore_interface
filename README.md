# kapps-triplestore-interface

[![PyPI version](https://img.shields.io/pypi/v/kapps-triplestore-interface)](https://pypi.org/project/kapps-triplestore-interface/)
![Python](https://img.shields.io/badge/python-%3E=3.12-blue)
![License](https://img.shields.io/badge/license-MIT-blue)

This library turns SPARQL queries and updates against a running GraphDB triplestore into
callable Python methods. Three research projects run it in production.

## Installation

```bash
pip install kapps-triplestore-interface
```

Or, from a clone of this repository:

```bash
uv sync
```

## Getting Started

`connect()` gives you a working, authenticated store. It takes where the store is, an auth
provider for your identity:

```python
from kapps_triplestore_interface import GDBTokenAuth, TripleStoreEndpoint, connect

my_db = connect(
    TripleStoreEndpoint(url="<your_graph_db_url>", dataset="<your_repository_id>"),
    GDBTokenAuth("<your_graph_db_user>", "<your_graph_db_password>"),
)

# Or everything from TRIPLESTORE_URL, TRIPLESTORE_DATASET, TRIPLESTORE_USERNAME and
# TRIPLESTORE_PASSWORD:
my_db = connect(TripleStoreEndpoint.from_env(), GDBTokenAuth.from_env())
```

`connect()` logs in and sends one probe to the dataset. So a broken configuration fails at the
start and not at the first request. A write by an identity that may only read fails at the
first write, as `TripleStoreAccessError`. The error types are those of the section "When a call
fails". The endpoint holds no secret, so you can log it. The provider renews its token before
it expires, and logs in again once when the store answers 401. The `GRAPHDB_*` variables are
read as a deprecated fallback of the `TRIPLESTORE_*` ones; the API reference lists the
providers and the variables.

## The store contract

Code above this interface types its store as `TripleStore`, which `connect()` returns. It
declares the operations that the object-graph mapper, the middleware and the use cases call on
a store, measured in their code, and no other; its docstring lists them. The GraphDB adapter,
`GraphDB`, implements each one. A test double satisfies the contract without inheriting from
it.

### The store's registries

A store keeps two registries that SPARQL does not cover. The contract has an operation for
each, so that no code above the interface calls a vendor's endpoint for them:

| Operation | What it does |
|---|---|
| `prefixes_get()` | Each prefix of the dataset, with the namespace IRI that it stands for, as a `dict`. The empty prefix is the key `""`. |
| `prefix_set(prefix, iri)` | Lets `prefix` stand for the namespace `iri`. A prefix that the dataset has already stands for `iri` afterwards. |
| `prefix_delete(prefix)` | Removes `prefix`. Every other prefix stays. |
| `shapes_set(data, content_type)` | Replaces the SHACL shapes that the store validates the dataset against with the document `data`, of the media type `content_type`, for example `text/turtle`. An empty document removes every shape. |
| `validate(shapes, content_type)` | Validates the whole dataset against the shapes document `shapes`, of the media type `content_type`, and returns the store's validation report verbatim (Turtle on GraphDB). It never changes the dataset or its shapes. A store without whole-dataset validation raises `TripleStoreNotSupportedError`. |

`""` is the empty prefix in each prefix operation. A failed operation raises; none returns a
flag.

**A store that has no such registry raises `TripleStoreNotSupportedError`**, and an operation
is never a silent no-op. An adapter that inherits `TripleStore` and does not implement a
registry raises it from the contract's own operations.

**`shapes_set` on a dataset without SHACL validation raises `TripleStoreNotSupportedError`**,
and writes nothing. GraphDB turns SHACL validation on only when a repository is created; on a
repository without it, the shapes would be stored as plain data that validates nothing. The
GraphDB adapter reads the repository's configuration to tell, and it refuses also when the
configuration does not say. On a dataset with SHACL validation it replaces the shapes graph
with `data` in one request, which the store applies whole or not at all. If the store refuses
it, because the data of the dataset violates the new shapes, `shapes_set` raises
`ShaclValidationError`, and the old shapes stay.

## What a write promises

The store answers a SPARQL update with success also when the update changes nothing. So the
five write functions that have a precondition send it inside the update itself:

| function | precondition with `check_exist=True` (the default) |
|---|---|
| `triples_add` | None of the triples exists yet. Triples that share a blank node are one structure. |
| `triples_delete`, `triple_delete` | All of the triples exist. |
| `triples_update`, `triple_update` | All of the old triples exist. |

`triples_add` and `triples_update` also take `absent_subjects`: IRIs that must not yet be the
subject of a triple in the target graph. A subject that occurs only as an object passes.

- **A normal return means "applied".** The store found the precondition true and committed the
  change. The function returns `True`.
- **A false precondition raises `PreconditionFailedError`**, and nothing is written. The error
  carries `.triples`, the triples that the precondition named, and `.named_graph`.
- **The scope is the explicit triples of the target graph.** The target graph is `named_graph`,
  or the default graph without the named graphs. A read (`triples_get`, `query`) sees all graphs
  and the inferred triples, but a delete cannot remove an inferred triple. So the precondition
  refuses an old triple that is only inferred.
- **A triple that is both explicit and inferred stays visible after a delete**, because a delete
  clears only the explicit flag.
- **Concurrent writers.** The store isolates only commits ("read committed"). Another writer can
  commit between the evaluation of the precondition and the commit of the write. Measured with
  two threads that replaced the same triple at the same time:
  - GraphDB Free 10.8.1 on a local machine: both writes applied in 50 of 50 rounds. With a
    start offset of 20 ms, both applied in 1 of 30 rounds.
  - GraphDB 10.8.5 Enterprise on a remote server: both writes applied in 0 of 50 rounds, in
    the default graph and in a named graph.

  The rate depends on the store and on its load, so a rate of 0 does not mean that the race
  cannot occur. An invariant that must hold under concurrent writers belongs in a SHACL shape:
  the store checks shapes at the commit.
- **`check_exist=False`** sends the write without a precondition and returns `True`. An
  unchecked update still applies only when its old triples match.
- **The receipt.** A checked write also writes one receipt triple into the graph
  `urn:x-kapps:write-receipts`, in the same update. The function reads the receipt and then
  removes it. If the process stops between the write and the removal, the receipt stays, with
  its time.
- **A write that gets no answer** (for example a timeout, or a connection that the store
  closed) raises `TripleStoreUnavailableError`, chained to the error of the HTTP client. The
  write is not sent again, and its receipt is not read: the store can still commit the write
  after that. A retry by the caller is safe: a checked write refuses a second application with
  `PreconditionFailedError`, and an insert or an import repeats as a no-op, because a graph is a
  set. The exceptions are blank nodes, which a second insert creates again, and a raw update
  that the caller writes itself.

## When the store refuses a write

A repository with SHACL validation checks a write when it commits it. If the data would
violate a shape, the store commits nothing of the write.
`GraphDB.query` then raises `ShaclValidationError`, and so do the functions that send their
update through it, for example `triples_add` and `triples_update`. `graph_clear` raises it too,
when the store refuses a clear because the remaining data would violate a shape. The error's
`report` is the store's validation report, unchanged:

```python
from kapps_triplestore_interface import ShaclValidationError

try:
    my_db.triples_add([(subject, predicate, obj)])
except ShaclValidationError as refused:
    print(refused.report)
```

The client logs a refusal only at DEBUG, so your code decides how loud it is. When
`GraphDB.query` or `graph_clear` gets any other error answer from the store, it logs it at ERROR
and raises a different type. To catch any error from this package, catch `TripleStoreInterfaceError` from
`kapps_triplestore_interface.exceptions`.

## When a call fails

Each error type tells your code one action, so you choose with `except` and do not read the
message. A message holds the store's answer unchanged.

| Type | What happened | Action |
|---|---|---|
| `TripleStoreResponseError` | The store answered with an error status that no subtype below covers. `status` is that status. | Repair |
| `AuthenticationError` | The store answered 401: it did not accept the credentials. | Repair |
| `TripleStoreAccessError` | The store answered 403: the identity has no access to the dataset. | Repair |
| `ShaclValidationError` | The store's shapes refused the write. `report` is the store's report. | Refused |
| `TripleStoreUnavailableError` | The store cannot be reached, it did not answer in time, or the connection dropped. | Retry |
| `PreconditionFailedError` | The precondition of a checked write was false, and nothing was written. | Refresh |
| `TripleStoreNotSupportedError` | The store, or the dataset, cannot do the operation. | Fix the call |
| `InvalidDatasetError` | The dataset does not exist on the store. | Repair |
| `InvalidQueryError`, `InvalidInputError`, `InvalidIRIError` | The call is incorrect. | Fix the call |

`AuthenticationError`, `TripleStoreAccessError` and `ShaclValidationError` are subtypes of
`TripleStoreResponseError`, and each carries the store's status.

Listing the datasets (`datasets_get`) and fetching a graph (`graph_get`) raise on an error
answer. They never return `None`.

## Running Tests

The test suite expects a running GraphDB instance and uses a dedicated test dataset. It builds its
store with `connect()`, as an application does.

Required environment variables for tests:

- `TRIPLESTORE_URL`
- `TRIPLESTORE_USERNAME`
- `TRIPLESTORE_PASSWORD`
- `TRIPLESTORE_TEST_DATASET`

Example:

```bash
export TRIPLESTORE_URL="http://localhost:7200"
export TRIPLESTORE_USERNAME="admin"
export TRIPLESTORE_PASSWORD="root"
export TRIPLESTORE_TEST_DATASET="test-repo"
uv run pytest tests -v
```

The suite wipes the dataset it connects to. It refuses a store that is neither on the local host
nor a bare container alias, unless `TRIPLESTORE_ALLOW_DESTRUCTIVE=1` says that the target is
disposable.

The test of `shapes_set` on a dataset without SHACL validation needs a second dataset on the
same store, created without SHACL validation, named by `TRIPLESTORE_TEST_DATASET_WITHOUT_SHACL`.
Without it, that test skips. The other tests of the shapes need SHACL validation in the test
dataset, and they leave it with no shapes.

The deprecated `GRAPHDB_*` names still work for the package, but the suite does not read them.
An application builds its store from `TRIPLESTORE_DATASET`, as in "Getting Started"; the suite
reads its dataset from `TRIPLESTORE_TEST_DATASET`.

## Contributing

Development happens in a private repository at KIT. This GitHub repository is a **publish
target**. A pull request opened here cannot be merged back. Raise an issue instead, or contact the
maintainers.

## Origin

This is a renamed fork of
[`JaFeKl/graph_db_interface`](https://github.com/JaFeKl/graph_db_interface) by Jan-Felix Klein,
last released as [`graph-db-interface` 2.0.1](https://pypi.org/project/graph-db-interface/) on
PyPI under an MIT license. It is maintained here, and changes since then are listed in
[CHANGELOG.md](CHANGELOG.md).

## Migration from graph-db-interface

1. Change your dependency from `graph-db-interface` to `kapps-triplestore-interface`.
2. Change imports from `from graph_db_interface import ...` to `from kapps_triplestore_interface import ...`.
3. If you catch it, change `GraphDBInterfaceError` to `TripleStoreInterfaceError`.

## License

The package is licensed under the [MIT license](LICENSE).

## Acknowledgements

This package is developed as part of the INF subproject of the
[CRC 1574: Circular Factory for the Perpetual Product](https://www.sfb1574.kit.edu/english/index.php).
This work is therefore supported by the Deutsche Forschungsgemeinschaft (DFG, German Research
Foundation) [grant-number: SFB-1574-471687386].
