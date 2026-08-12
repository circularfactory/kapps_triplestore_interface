# kapps-triplestore-interface

[![PyPI version](https://img.shields.io/pypi/v/kapps-triplestore-interface)](https://pypi.org/project/kapps-triplestore-interface/)
![Python](https://img.shields.io/badge/python-%3E=3.12-blue)
![License](https://img.shields.io/badge/license-MIT-blue)

This library turns SPARQL queries and updates against a running GraphDB triplestore into
callable Python methods. Three research projects run it in production.

## Origin

This is a renamed fork of [`graph-db-interface`](https://github.com/JaFeKl/graph_db_interface)
by Jan-Felix Klein.

- **Origin:** [`JaFeKl/graph_db_interface`](https://github.com/JaFeKl/graph_db_interface) — MIT
  licensed, last released as
  [`graph-db-interface` 2.0.1](https://pypi.org/project/graph-db-interface/) on PyPI.
- **This release:** the `dev_semantic_middleware` branch of
  [`SAWeindel/graph_db_interface`](https://github.com/SAWeindel/graph_db_interface), which
  carries five commits by Sören Weindel and Etienne Hoffmann that are in no released
  `graph-db-interface`. They are listed in [CHANGELOG.md](CHANGELOG.md).

The licence is MIT. Jan-Felix Klein's 2025 copyright notice is retained — a condition of the
licence this fork relies on, not a courtesy — alongside a 2026 notice for Etienne Hoffmann and
Sören Weindel.

## Migration from graph-db-interface

Three edits, and nothing else moves:

1. Change your dependency from `graph-db-interface` to `kapps-triplestore-interface`.
2. Change imports from `from graph_db_interface import ...` to `from kapps_triplestore_interface import ...`.
3. If you catch it, change `GraphDBInterfaceError` to `TripleStoreInterfaceError`.

The classes `GraphDB` and `GraphDBCredentials`, the flag `use_gdb_token` and the word
*repository* all stay, deliberately. A GDB token is a GraphDB-only mechanism — Basic auth
returns 401 against it, and the token comes from `rest/login` — so a backend-neutral name for
it would hide a vendor mechanism behind a neutral word rather than abstract it. *Repository* is
RDF4J's own term, and RDF4J is what this library speaks. And an abstraction never tested
against a second implementation is not one: when a second backend arrives, a class is *added*,
and `GraphDB` stays a correct name for the GraphDB implementation.

### Why the first release is 2.1.0

It is the same mature library under a new name, so `2.x` tells the truth about it where `0.x`
would falsely say *I may break you*. Minor rather than patch because commit `65157c5` adds a
feature.

Not 3.0.0: semver's breaking-change rule governs upgrades *within* one distribution name, and
no such upgrade path exists here. Nobody is bumped from `graph-db-interface` to this — they
must edit their manifest, and that edit is the migration signal.

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

This repository is a **publish target**. It receives one commit per release, cut from a private
development repository, so a pull request opened here has no shared history to merge into and
cannot be merged. Please open an issue instead.

Improvements that belong to the library this was forked from are better sent to its origin,
[`JaFeKl/graph_db_interface`](https://github.com/JaFeKl/graph_db_interface).

## License

The package is licensed under the [MIT license](LICENSE).

## Acknowledgements

This package is developed as part of the INF subproject of the [CRC 1574: Circular Factory for the Perpetual Product](https://www.sfb1574.kit.edu/english/index.php). This work is therefore supported by the Deutsche Forschungsgemeinschaft (DFG, German Research Foundation) [grant-number: SFB-1574-471687386]
