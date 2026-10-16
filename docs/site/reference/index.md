# API reference

Generated from the source by `sphinx.ext.autodoc`, one page per public module (19 modules).
Members without a docstring are listed too, with their signatures. Deprecated names are left
out; the changelog lists them.

:::{note}
The package's top-level namespace re-exports the names most code imports: `connect`, `TripleStore`, `GraphDB`, `IRI`, `SPARQLQuery`, …
Each is documented once, on the page of the module that defines it.
:::

```{toctree}
:caption: Core
:maxdepth: 1

connection
store
auth
exceptions
graph_db
sparql_query
```

```{toctree}
:caption: Queries
:maxdepth: 1

queries/checked_write
queries/named_graph
queries/ontology_helpers
queries/rdf4j/graph_store
queries/triple_multi
queries/triple_single
```

```{toctree}
:caption: Utilities
:maxdepth: 1

utils/iri
utils/pretty_print
utils/processing
utils/types
utils/utils
utils/xsd_typemap
```

```{toctree}
:caption: Kafka
:maxdepth: 1

kafka/kafka_manager
```
