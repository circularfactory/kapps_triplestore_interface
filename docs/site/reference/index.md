# API reference

Generated from the source by `sphinx.ext.autodoc`, one page per public module (16 modules).
Members without a docstring are listed too, with their signatures.

:::{note}
The package's top-level namespace re-exports the names most code imports: `GraphDB`, `GraphDBCredentials`, `IRI`, `SPARQLQuery`, …
Each is documented once, on the page of the module that defines it.
:::

```{toctree}
:caption: Core
:maxdepth: 1

exceptions
graph_db
sparql_query
```

```{toctree}
:caption: Queries
:maxdepth: 1

queries/named_graph
queries/ontology_helpers
queries/rdf4j/graph_store
queries/triple_multi
queries/triple_single
```

```{toctree}
:caption: Utilities
:maxdepth: 1

utils/graph_db_credentials
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
