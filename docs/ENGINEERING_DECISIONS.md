# HealthGrid — Engineering Decisions

This document records the main architectural and implementation decisions visible in the repository. It distinguishes implemented behavior from assumptions that should be reviewed when redeploying the platform.

## 1. Project context

HealthGrid is a completed end-to-end educational healthcare data platform built with synthetic data. It was originally developed as **CareSync** and later renamed **HealthGrid**. The original Azure environment was successfully executed; some cloud resources may subsequently have been decommissioned to avoid ongoing cost.

The repository still contains legacy CareSync identifiers in Databricks catalog names, notebook paths, SQL comments, and ADF notification text. These are historical deployment references. The original architecture image is intentionally preserved unchanged.

## 2. Azure Data Factory for orchestration

**Decision:** Use Azure Data Factory (ADF) to coordinate source extraction, landing, Databricks processing, audit updates, and notifications.

**Rationale:**
- Separates orchestration from transformation logic.
- Supports independent source branches for PostgreSQL and partner CSV files.
- Uses reusable child pipelines and table-level metadata.
- Provides a central run identifier and audit trail across pipeline stages.

**Trade-off:** ADF exports contain environment-specific linked-service references, notebook paths, storage locations, and global parameters. A redeployment must configure these references for the target environment rather than assuming the exported identifiers are portable.

## 3. Metadata-configured source ingestion

**Decision:** Store source configuration in Azure SQL control tables.

The ctrl.table_config table describes source system, source object or file, landing path, Bronze and Silver targets, load strategy, watermark column, merge keys, processing stage, and active status.

**Rationale:**
- Enables a common ingestion framework for PostgreSQL tables and ADLS CSV feeds.
- Makes source activation and load strategy configurable without duplicating an entire pipeline for each object.
- Keeps execution audit and watermark state outside the transformation notebooks.

**How this applies across the layers:** Metadata drives the end-to-end framework, including Gold. The Gold pipeline queries active `SILVER_TO_GOLD` rows from `ctrl.table_config`, iterates over those rows, and constructs the Databricks notebook path from each row's `gold_table_name`. This means the Gold target selection and execution are metadata-driven, just as source-to-Silver ingestion is configured from metadata. The individual analytical transformation SQL remains implemented in the corresponding Gold notebook; metadata selects and orchestrates the configured transformation rather than storing all transformation SQL inside the control table.

## 4. Load strategies

The framework supports three configured write strategies:

| Strategy | Implemented behavior | Main consideration |
|---|---|---|
| FULL | Overwrite the Silver target with the current processed batch | Appropriate for small reference datasets when the landing batch contains the complete source snapshot |
| APPEND | Append the current batch to the Silver target | Requires a clear file-delivery and duplicate-handling policy |
| MERGE | Match configured business keys; update matches and insert new records | Requires valid keys, source deduplication, and a defined update-ordering policy |

The sample configuration uses FULL for hospitals, doctors, and insurance providers; MERGE for patients; and APPEND for laboratory results.

## 5. Watermark-based extraction

**Decision:** Use a persisted watermark for incremental source extraction rather than implementing a full CDC service.

The ADF pipeline reads the stored watermark for non-FULL loads and filters the PostgreSQL source using the configured watermark column. The control value is advanced after the Bronze-to-Silver processing path succeeds.

**Rationale:** This provides a relatively simple incremental pattern for the sample source systems and keeps progress state in a central control database.

**Correctness assumptions and limitations:**
- Source update timestamps must be maintained reliably.
- The extraction predicate uses a strict greater-than comparison, so records sharing an already-processed timestamp need deliberate handling.
- Late-arriving updates, hard deletes, source clock differences, and timestamp collisions are not equivalent to CDC and need explicit policies.
- The exported pipeline advances the stored watermark using the current UTC time rather than calculating the maximum source timestamp observed in the batch. This should be reviewed against source timestamp semantics and tested for boundary conditions before a new production deployment.
- Watermark advancement must remain downstream of successful processing; failed or partially completed runs should not move the checkpoint forward.

## 6. Bronze landing and batch context

**Decision:** Retain source extracts in ADLS landing paths and append them to Bronze Delta tables with batch metadata.

The Landing-to-Bronze notebook:
- Reads CSV or Parquet from a timestamped landing directory.
- Adds landing_timestamp and insert_timestamp.
- Appends the batch to the corresponding Bronze table.

The Bronze-to-Silver notebook filters by the same landing timestamp so the current batch can be processed independently.

**Trade-off:** The landing timestamp gives the processing pipeline a batch boundary, but append-only Bronze ingestion can retain duplicate batches if the same landing path is replayed. Replay and duplicate-delivery behavior should be tested and controlled operationally.

## 7. Silver transformation

**Decision:** Use a shared Databricks notebook to apply FULL, APPEND, or MERGE behavior to configured Silver tables.

For MERGE, the notebook validates that merge keys are supplied and exist in the incoming DataFrame before building the Delta MERGE statement.

**Trade-off:** The merge updates matched records using the incoming batch. The current implementation does not define a source-version comparison or deterministic tie-breaker for multiple incoming rows with the same business key. Source deduplication and ordering should be established where feeds can contain repeated keys.

## 8. Gold analytical modeling

**Decision:** Publish three purpose-built Gold datasets through a metadata-driven Gold orchestration stage rather than exposing raw Silver tables directly to reporting consumers.

- patient_360: patient-level records enriched with hospital and insurance details and pre-aggregated laboratory activity.
- hospital_daily_summary: hospital/day laboratory volume, distinct patients, doctor counts, abnormal and critical counts and rates, and previous-day comparison.
- lab_test_trends: monthly test volumes, abnormal and critical counts and rates, and month-over-month abnormal-rate movement.

**Grain and join considerations:**
- patient_360 is intended to have one row per patient.
- Laboratory activity is aggregated to patient grain before joining to patient records, preventing one patient row from multiplying by the number of laboratory tests.
- hospital_daily_summary is grouped by hospital and test date.
- lab_test_trends is grouped by test name and calendar month.

Gold notebooks rebuild their targets using CREATE OR REPLACE TABLE. This is a full rebuild pattern, not an incremental Gold merge.

## 9. Calendar dimension

**Decision:** Build a reusable Silver calendar table spanning 1940-01-01 through 2030-12-31.

The calendar provides date keys, day/week/month/quarter/year attributes, period boundaries, weekend flags, and leap-year indicators. Gold notebooks use it for date enrichment.

**Consideration:** Extend the date range when the source data or reporting horizon moves beyond the configured boundaries.

## 10. Audit and notification controls

The control framework records table-level stage status, ADF run ID, record count, start time, and end time. A separate notification pipeline reads audit records and posts a status payload to a Logic Apps endpoint.

**Operational consideration:** The exported master pipeline uses Completed dependencies to start Gold after both source branches finish, and to start notification after Gold finishes. A completed activity can have succeeded, failed, or been skipped status. Validate that the intended failure-propagation and notification behavior is preserved in the deployed factory; do not assume that completion alone means all upstream work succeeded.

## 11. Security and data scope

The checked-in data is synthetic and the project is educational. Credentials should be supplied through secure linked-service configuration and Azure Key Vault references, not committed in source control. Any real-world adaptation would require privacy, access-control, retention, encryption, audit, and regulatory controls appropriate to the jurisdiction and data classification.

## 12. Deployment and operational decisions

- Treat source-table DDL containing DROP statements as a controlled initialization/reset script, not a non-destructive migration.
- Configure environment-specific storage, catalog, schema, notebook, linked-service, and notification references together.
- Preserve the original architecture diagram; update explanatory documentation around it rather than altering the image.
- Run the validation plan and reconcile source, Bronze, Silver, Gold, and audit counts after redeployment.
- Keep the project status accurate: it was successfully executed end-to-end in its original environment, even if cost-saving cleanup means that environment is no longer active.

## 13. Interview discussion prompts

1. Why use metadata-configured ingestion, and which parts of the platform remain code-defined?
2. What guarantees does a timestamp watermark provide, and where can it miss changes?
3. How would you make landing-to-Bronze replay safe?
4. How would you handle late-arriving updates, hard deletes, and equal timestamps?
5. What is the grain of each Gold dataset, and how do the joins preserve it?
6. How would you validate that an ADF master run cannot publish Gold outputs from failed source branches?
7. What evidence would you collect to demonstrate a successful end-to-end run?
