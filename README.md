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
