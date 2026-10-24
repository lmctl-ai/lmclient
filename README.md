# lmdb

**A scriptable JDBC database client for queries, exports, schema inspection and visual results.**

| Query chart | ER diagram | Schema map |
| --- | --- | --- |
| <img src="docs/images/sqlite_sales_trend.png" width="290" alt="SQLite monthly sales trend"> | <img src="docs/images/er_diagram.png" width="290" alt="JDBC entity relationship diagram"> | <img src="docs/images/lmdb_schema_map.png" width="290" alt="Database schema map"> |
| Monthly revenue grouped by SQL, then plotted with lmplot<br>`lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/sqlite_sales_trend.lms` | Primary and foreign keys discovered through JDBC metadata<br>`lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/er_diagram.lms` | Tables and columns queried from JDBC metadata<br>`lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/schema_map.lms` |

## Quick start

Install the release for your platform, then run a complete example from any empty directory:

```sh
lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/sqlite_sales_trend.lms
```

The example creates an in-memory SQLite database, writes `data/sqlite_sales_trend.csv`, and renders `images/sqlite_sales_trend.png`. The database credentials never enter the output or logs. Linux release binaries require dynamic glibc >= 2.35.

## Examples

Every example is self-contained and binds lmdb plus lmplot by release. Each command writes a CSV result and a PNG chart.

| Example | Story | Run |
| --- | --- | --- |
| `sqlite_sales_trend.lms` | Monthly revenue trend | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/sqlite_sales_trend.lms` |
| `sqlite_inventory.lms` | Warehouse inventory value | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/sqlite_inventory.lms` |
| `sqlite_air_quality.lms` | Rolling PM2.5 average | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/sqlite_air_quality.lms` |
| `sqlite_flights.lms` | Joined route delay ranking | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/sqlite_flights.lms` |
| `h2_budget.lms` | Planned versus actual spend | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/h2_budget.lms` |
| `h2_latency.lms` | API latency envelope | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/h2_latency.lms` |
| `h2_orders.lms` | Order funnel conversion | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/h2_orders.lms` |
| `h2_cohort.lms` | Cohort retention matrix | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/h2_cohort.lms` |
| `duckdb_weather.lms` | Seasonal station temperatures | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/duckdb_weather.lms` |
| `duckdb_energy.lms` | Cumulative energy budget | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/duckdb_energy.lms` |
| `duckdb_returns.lms` | Rolling market returns | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/duckdb_returns.lms` |
| `duckdb_population.lms` | Regional population density | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/duckdb_population.lms` |
| `schema_map.lms` | JDBC tables, columns and primary keys | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/schema_map.lms` |
| `er_diagram.lms` | JDBC primary and foreign key relationship | `lmctl autorun https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/er_diagram.lms` |

## JDBC host API

Inside an lmscript program, bind the host with `_dsl_ cli="lmdb" install="github:lmctl-ai/lmdb@latest"`. `connect(url)` returns a connection; `exec(sql)` runs DDL or DML; `query(sql)` returns a result. Results expose `csv(path)`, `json(path)`, `rows()`, `number(row, column)` and `text(row, column)`. `tables()`, `columns(table)`, `keys(table)` and `indexes(table)` expose JDBC metadata for schema reports. Use environment variables or a protected credentials file for server credentials.

## Drivers

The native distribution bundles PostgreSQL, SQLite-JDBC, H2, DuckDB and Microsoft SQL Server JDBC drivers. MySQL and MariaDB drivers are not bundled; on the JVM, pass a user supplied driver jar through the CLI build workflow. The release includes driver notices and the GraalVM runtime notice.

## Build

```sh
mvn -q verify
scripts/build-native.sh
```

Native release names are `lmdb-<os>-<arch>` with one executable per platform. The test suite exercises every bundled driver, schema metadata, CSV/JSON export, credential redaction and the five native platform binaries.
