# HealthGrid — ADF Source Extraction Contract

## Scope

This document describes the metadata-to-source path implemented by:

- \`PL_SOURCE_TO_SILVER_MAIN\`: validates the requested source system and selects active source-to-Silver metadata rows.
- \`PL_SOURCE_TO_SILVER_INNER\`: validates the selected table ID and metadata, reads the required watermark when applicable, extracts the source, and hands the timestamped landing batch to the Databricks notebooks.

The source pipeline is metadata-driven. Source table selection and supported load strategies come from \`ctrl.table_config\`; dataset-specific transformation logic remains in Databricks.

## Dispatcher contract

The main pipeline accepts only \`neon_postgres\` or \`adls_csv\`. Its metadata query selects only rows where:

- \`is_active = 1\`
- \`stage = 'SOURCE_TO_SILVER'\`
- \`source_system\` equals the validated source-system parameter.

The inner pipeline receives \`table_id\` as an integer and rejects non-positive values before querying metadata. Its lookup explicitly projects the columns needed by extraction, rather than selecting every control-table column. It rechecks that the selected row is active and belongs to \`SOURCE_TO_SILVER\`, preventing a Gold-stage or inactive row from being dispatched as a source.

Before source Copy, the pipeline validates:
- Supported source system and load strategy.
- PostgreSQL schema/table identifiers and, for incremental loads, watermark column and non-negative lookback.
- ADLS source path, CSV file format, and FULL/APPEND strategy.
- The branch-specific required metadata fields.

Invalid or unsupported metadata fails explicitly before Copy or notebook execution.

## PostgreSQL query construction

The Copy source query is assembled from the configured schema, table, load type, watermark column, previous checkpoint, lookback, and fixed upper bound.

- Schema, table, and watermark-column names are double-quoted identifiers.
- Embedded double quotes are escaped by doubling them before interpolation.
- String values such as the parent \`adf_run_id\` are escaped before SQL literal interpolation in audit and manifest statements.
- The selected table ID is numeric, not a caller-controlled SQL string.
- The query retains a metadata-driven projection (\`SELECT *\` from the selected source table) and does not hardcode a schema or table name.

For FULL, no watermark predicate is appended. For timestamp-incremental PostgreSQL loads, the query uses the half-open interval:

\`[previous_watermark - watermark_lookback_minutes, captured_run_upper_bound)\`

The lower boundary is inclusive; the upper boundary is exclusive. The configured five-minute patient lookback intentionally re-reads a short overlap. Silver MERGE uses \`patient_id\` and the configured \`updated_at\` source-version column so identical equal-version overlap rows are no-ops.

## Watermark validation and checkpoint contract

Before an incremental PostgreSQL Copy, ADF queries the selected active metadata row with a LEFT JOIN to \`ctrl.watermark\`. The lookup returns an explicit validity flag. A missing watermark row, NULL value, or value that cannot convert to \`DATETIME2(6)\` fails before source extraction.

The pipeline captures one UTC upper bound for the table run and reuses that value in both the source query and checkpoint update. It does not use pipeline completion time as the checkpoint.

After Bronze-to-Silver succeeds, the pipeline finalizes any current-run CSV manifest rows and applies the applicable watermark branch. The checkpoint update is monotonic: it retains an already newer value rather than moving backwards. It must update exactly one row for the selected table; zero or multiple rows raise an error. The source SUCCESS audit update depends on successful manifest finalization and the applicable checkpoint activity.

An incremental NO_DATA result skips the Silver write and checkpoint advancement. FULL sources do not use a timestamp watermark. ADLS CSV source selection is driven by \`ctrl.file_ingestion_manifest\`, not by row-level \`reported_at\`.

## Landing batch contract

PostgreSQL Copy writes Parquet to the configured ADLS landing filesystem using a batch path composed of source system, source table, and a run-unique timestamp/ADF run ID. The same \`start_time\` is passed to Landing-to-Bronze and Bronze-to-Silver so both stages identify the exact same batch.

The pipeline's Copy completion and notebook output must be inspected separately. A Copy-level no-file/error condition can occur before the notebook handles NO_DATA; it is not evidence of a successful empty extraction. Runtime tests in a restored environment must confirm the connector's behavior for empty PostgreSQL query results, timestamp precision, query expressions, and actual Parquet output.

## Operational limitations

- The timestamp watermark is not CDC and does not capture hard deletes.
- Updates that become visible or are backdated beyond the configured overlap can still be missed.
- A source that does not maintain \`updated_at\` reliably can violate the version-ordering contract.
- Quoting protects identifier boundaries; it does not make arbitrary metadata trustworthy. Only authorized operators should modify source metadata.
- Static CI verifies exported definitions and contracts. It does not execute PostgreSQL queries, ADF expression evaluation, source connectors, or landing writes.

## Runtime validation evidence

Use the scenarios in [the Validation Plan](VALIDATION_PLAN.md), particularly ADF-18 through ADF-24 and WMR-01 through WMR-16. Retain:
- Selected table ID, source system, stage, load type, and relevant configuration values.
- Generated/executed PostgreSQL query and the actual source Copy activity output.
- Previous checkpoint, configured lookback, captured upper bound, selected row count, and post-run checkpoint.
- Landing folder, Parquet files/schema, landing timestamp, and Databricks notebook parameters/results.
- Audit outcome and before/after source, Bronze, and Silver counts.

A static workflow pass is necessary repository evidence; a live ADF/Databricks run and data reconciliation are separate acceptance evidence.

## Landing batch file discovery contract

The Landing-to-Bronze notebook lists only the exact batch folder selected by ADF. It ignores directories and hidden/Spark marker files, then accepts only `.csv` files for CSV metadata or `.parquet` files for Parquet metadata (an omitted format retains the Parquet default). Visible files with an unexpected extension fail the batch rather than being silently treated as an empty extract. A folder with no eligible data files follows the documented NO_DATA rules; a missing landing volume or access failure remains a deployment/runtime error.
