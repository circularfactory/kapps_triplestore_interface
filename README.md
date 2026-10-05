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

The package uses a single class named `GraphDB`. To use the interface, create an object from
this class:

```python
from kapps_triplestore_interface import GraphDB, GraphDBCredentials

credentials = GraphDBCredentials(
    base_url="<your_graph_db_url>",
    username="<your_graph_db_user>",
    password="<your_graph_db_password>",
    repository="<your_selected_repository_id>",
)

my_db = GraphDB(credentials=credentials)
```

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
- **A transport error** (for example a timeout, or a connection that the store closed) raises
  the `requests` exception unchanged, for example `requests.Timeout` or
  `requests.ConnectionError`. The write is not sent again, and its receipt is not read: the
  store can still commit the write after that.

## When the store refuses a write

A repository with SHACL validation checks a write when it commits it. If the data would
violate a shape, the store commits nothing of the write.
`GraphDB.query` then raises `ShaclValidationError`, and so do the functions that send their
update through it, for example `triples_add` and `triples_update`. `clear_graph` raises it too,
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
`GraphDB.query` or `clear_graph` gets any other error answer from the store, it logs it at ERROR
and raises a different type. To catch any error from this package, catch `TripleStoreInterfaceError` from
`kapps_triplestore_interface.exceptions`.

## Running Tests

The test suite expects a running GraphDB instance and uses a dedicated test repository.

Required environment variables for tests:

- `GRAPHDB_URL`
- `GRAPHDB_USERNAME`
- `GRAPHDB_PASSWORD`
- `GRAPHDB_TEST_REPOSITORY`

Example:

```bash
export GRAPHDB_URL="http://localhost:7200"
export GRAPHDB_USERNAME="admin"
export GRAPHDB_PASSWORD="root"
export GRAPHDB_TEST_REPOSITORY="test-repo"
uv run pytest tests -v
```

Note: application/runtime credentials loaded via `GraphDBCredentials.from_env()` still use
`GRAPHDB_REPOSITORY` by default.

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
