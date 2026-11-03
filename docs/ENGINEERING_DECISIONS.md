# HealthGrid — Engineering Decisions

This document records the main architectural and implementation decisions visible in the repository. It distinguishes implemented behavior from assumptions that should be reviewed when redeploying the platform.

## 1. Project context

HealthGrid is a completed end-to-end educational healthcare data platform built with synthetic data. It was originally developed as **CareSync** and later renamed **HealthGrid**. The original Azure environment was successfully executed; some cloud resources may subsequently have been decommissioned to avoid ongoing cost.

The repository's notebooks use the `healthgrid` Unity Catalog catalog, the `healthgrid.landing.landing_volume` landing Volume, and ADF notebook paths under `/Shared/HealthGrid/`. Azure endpoint and compute-specific values are deployment placeholders in the linked-service exports. The original architecture image is intentionally preserved unchanged.

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

The `ctrl.table_config` table describes source system, source object or file, landing path, Bronze and Silver targets, load strategy, optional timestamp watermark column, merge keys, processing stage, and active status. `ctrl.file_ingestion_manifest` tracks ADLS CSV file versions independently of PostgreSQL timestamp checkpoints.

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

The ADF pipeline reads the stored watermark for non-FULL PostgreSQL loads and filters the source using the configured watermark column. Metadata supplies a per-object `watermark_lookback_minutes` value. For the current patients MERGE source it is set to five minutes. At the start of each source-table run, ADF captures a fixed UTC upper bound; the source query reads the half-open interval `[previous watermark - lookback, run-start upper bound)`. The persisted checkpoint advances to that captured upper bound only after Bronze-to-Silver succeeds. A monotonic SQL update prevents an older overlapping run from moving the checkpoint backwards. ADLS CSV feeds continue to use their file-version manifest rather than this timestamp watermark.

**Rationale:** The fixed upper bound prevents records updated after extraction starts from being hidden behind a checkpoint taken at pipeline completion. The configurable overlap helps recover records that become visible shortly after extraction or whose source timestamp is slightly behind the prior checkpoint. The patients Silver MERGE is version-aware and replay-safe for this bounded re-read.

**Correctness assumptions and limitations:**
- This timestamp watermark pattern applies to PostgreSQL sources in this project; ADLS CSV selection uses the per-file manifest.
- The supplied PostgreSQL source DDL stores timestamp-without-time-zone values in UTC and installs a `BEFORE UPDATE` trigger on `patients` so every row update refreshes `updated_at`, even when a writer omits it. External sources must follow the same UTC/update-timestamp contract and avoid backdating updates outside the documented lookback.
- The overlap is a mitigation, not a completeness guarantee. Updates arriving more than five minutes late, unmaintained timestamps, hard deletes, and some clock/transaction anomalies can still be missed.
- The source query uses an inclusive lower bound and exclusive run-start upper bound. Re-reading boundary rows is expected; the MERGE's key/version checks provide idempotent handling for unchanged replays.
- Checkpoint advancement is downstream of successful processing and records the fixed run-start upper bound, not pipeline completion time or the maximum source timestamp found in the batch.
- This remains watermark-based extraction, not log-based CDC. If hard-delete capture or a strict no-loss change history is required, use source CDC/logical replication or an explicit soft-delete/change-event contract.

Runtime boundary and concurrency scenarios remain in the validation plan and require a restored Azure environment.

## 6. Bronze landing and batch context

**Decision:** Retain source extracts in ADLS landing paths and append them to Bronze Delta tables with batch metadata.

The Landing-to-Bronze notebook:
- Reads CSV or Parquet from a timestamped landing directory.
- Adds landing_timestamp and insert_timestamp.
- Appends the batch to the corresponding Bronze table.

The Bronze-to-Silver notebook filters by the same landing timestamp so the current batch can be processed independently.

**Landing-to-Bronze safeguards:** The notebook validates source system/table identifiers, the ADF landing timestamp, load strategy, and source file format before constructing the landing path or reading data. Missing/unknown load strategies fail rather than defaulting to FULL. It rejects source columns that collide case-insensitively with reserved `landing_timestamp` and `insert_timestamp` fields. For an existing Bronze target, column names are compared case-insensitively and source fields must match the established schema and data types; missing/added/changed fields fail closed pending a reviewed migration. Existing technical batch columns are also checked for presence and expected types. An exact landing timestamp already in Bronze is rejected before another append.

**Trade-off:** The landing timestamp gives the processing pipeline a batch boundary, and exact same-timestamp batches are blocked before another Bronze append. This is not a distributed concurrency lock or business-row deduplication mechanism: identical source events delivered with a different landing timestamp can still be appended. The CSV manifest additionally skips already-processed file versions and blocks unresolved prior-run copies. It is not a distributed exactly-once transaction; whole-file replacement under APPEND can still duplicate rows.

**Silver write contract:** The shared Bronze-to-Silver notebook treats the configured load strategy as required metadata and rejects missing/unknown values instead of assuming FULL. FULL replaces the target from the current non-empty batch; APPEND adds the batch but does not deduplicate business events across distinct batch IDs; MERGE uses configured business keys and a DATE/TIMESTAMP source version.

**MERGE safeguards:** Source business keys are checked for nulls and duplicates, and source versions for nulls. If a target exists, the notebook requires matching column names and data types, rejects case-insensitive name collisions, and checks target key uniqueness and version nullability. A strictly newer source version updates the target; an older version is skipped; an identical equal-version business payload is a no-op; and an equal-version payload conflict fails for reconciliation. Technical landing/insert/update timestamps are excluded from equal-version payload comparison.

**Failure behavior:** The notebook accepts the explicit ADF DATA/NO_DATA status. NO_DATA exits without a Silver write; if ADF reports DATA but the timestamped Bronze batch is empty, the notebook fails so downstream checkpoint logic cannot mistake a missing batch for a successful data load. Table and landing-batch identifiers are restricted to safe formats before use in Spark statements.

These are code-level safeguards, not a distributed exactly-once guarantee. APPEND remains sensitive to a source re-delivering the same business events under a different landing timestamp. Repository CI statically checks the contracts and parses notebook Python code; Delta runtime behavior requires validation in a restored Databricks workspace.


## 7. Per-file manifest for ADLS CSV feeds

**Decision:** Track file versions in `ctrl.file_ingestion_manifest` instead of using a timestamp watermark for CSV selection.

ADF lists direct child items in the configured source folder, filters CSV files, reads each file's size, last-modified time, and content MD5 where available, then checks its manifest identity. The file moves through `IN_PROGRESS`, `COPIED`, and `PROCESSED`; a Copy failure is recorded as `FAILED`. The manifest is finalized as `PROCESSED` only after Bronze-to-Silver succeeds.

**State-transition and retry safeguards:** Each per-file `COPIED` and `FAILED` update is scoped to the current ADF run and exact file-version identity, and asserts that exactly one manifest row transitioned. The updates accept their destination state as well as the expected prior state, making an ADF Script-activity retry idempotent after an acknowledgement loss. Finalization runs in a SQL transaction after Bronze-to-Silver succeeds; it transitions `COPIED` rows to `PROCESSED` and refuses to complete while any current-run row remains `IN_PROGRESS`, `COPIED`, or `FAILED`. A no-new-file/no-data run may legitimately have zero manifest rows. These checks strengthen SQL-side state consistency but do not make Delta writes and Azure SQL manifest updates one atomic distributed transaction.

**Rationale:**
- File modification time is a delivery property; `reported_at` is a business event timestamp inside the lab-results data. They are not interchangeable.
- A file-level identity makes it possible to skip the same processed version on later runs.
- A previous-run `IN_PROGRESS` or `COPIED` state blocks automatic recopy until downstream writes are reconciled, reducing the risk of duplicate APPEND processing.

**Trade-offs and limits:**
- The identity includes path, name, last-modified timestamp, size, and optional content MD5. If MD5 is unavailable and content changes without size or timestamp changing, the replacement cannot be detected.
- A changed whole-file snapshot is a new file version. APPEND may duplicate rows already contained in the older version; the configured feed should therefore be immutable/additive or have row-level deduplication.
- A crash between Delta processing and Azure SQL manifest finalization is not an atomic transaction. The `COPIED` state intentionally forces operator reconciliation rather than automatic replay.
- The first run against an empty manifest processes every eligible source file. Existing populated targets require a manifest baseline before enabling this path.

## 8. Silver transformation

**Decision:** Use a shared Databricks notebook to apply FULL, APPEND, or MERGE behavior to configured Silver tables.

For MERGE, ADF passes the configured `watermark_column` as the source-version field. The shared notebook requires that field to be a DATE or TIMESTAMP, rejects null business keys, duplicate source keys, null source versions, invalid target keys, and source/target schema mismatches before mutation. It does not silently choose a winner when multiple source rows share a business key.

Matched rows are updated only when the incoming source version is strictly newer than the target version. Equal-version rows with identical business payloads are treated as safe replays; equal-version rows with changed business payloads fail for reconciliation. Older source versions are counted and skipped. The current MERGE configuration is the PostgreSQL `patients` object, using `patient_id` as the business key and `updated_at` as the source version.

## 9. Gold analytical modeling

**Decision:** Publish three purpose-built Gold datasets through a metadata-driven orchestration stage rather than exposing raw Silver tables directly to reporting consumers.

| Dataset | Grain | Main transformation |
|---|---|---|
| patient_360 | patient_id | Aggregate laboratory activity to patient grain before left-joining patient, hospital, and insurance-provider attributes |
| hospital_daily_summary | hospital_id, summary_date | Aggregate event counts and distinct patients/doctors by hospital/date, enrich with calendar attributes, and calculate observed-row volume movement |
| lab_test_trends | test_name, year, month | Aggregate event counts and rates by test/month and calculate observed-month abnormal-rate movement |

**Grain and join considerations:**
- The patient model aggregates laboratory events before joining, protecting patient grain from the one-to-many event relationship. The reference joins assume unique hospital and provider IDs; a duplicate lookup can multiply patient rows and is now detected by the output-grain check.
- The hospital model's active_doctor_count counts distinct doctor IDs found in laboratory events, not the full hospital doctor roster.
- Both time-series models use LAG over rows that exist in the aggregate output. They do not generate missing calendar dates/months with zero measures. Thus prev_day_total_tests means previous available hospital-date observation (the legacy column name is retained), and the lab trend prior value means previous available month for that test.
- test_volume_change_pct is relative percentage change from the prior observed hospital-date row. abnormal_rate_change_pct is the difference between two abnormal rates in percentage points, not a relative percentage change.
- Patient age is calculated using datediff(current_date(), date_of_birth) / 365.25 when the table is rebuilt, so it is an approximate age as of rebuild time.

**Gold output contracts:** Each notebook now checks required columns, non-null and unique grain keys, and basic count/rate bounds after rebuilding its table. These checks make key model assumptions executable and fail the notebook when the output violates the declared grain or metric constraints. They have not yet been executed in a restored Azure/Databricks environment; static repository CI does not constitute runtime proof.

Gold notebooks rebuild their targets using CREATE OR REPLACE TABLE. This is a full rebuild pattern, not an incremental Gold merge. Validate target consistency and recovery if a notebook fails during publication; failure-injection and parallel-execution scenarios remain in the validation plan.

## 10. Calendar dimension

**Decision:** Build a reusable Silver calendar table spanning 1940-01-01 through 2030-12-31.

The calendar provides date keys, day/week/month/quarter/year attributes, period boundaries, weekend flags, and leap-year indicators. Gold notebooks use it for date enrichment.

**Consideration:** Extend the date range when the source data or reporting horizon moves beyond the configured boundaries.

## 11. Audit and notification controls

The control framework records table-level stage status, ADF run ID, record count, start time, and end time. The natural audit key is `(adf_run_id, table_id, stage)`. A unique constraint enforces one summary row per parent run/object/stage, and `MERGE ... WITH (HOLDLOCK)` makes IN_PROGRESS creation idempotent for retry. Final updates are stage-scoped. This table summarizes the latest attempt; ADF run/activity history retains individual attempt details. A separate notification pipeline reads audit records and posts a status payload to a Logic Apps endpoint.

**Operational consideration:** The master pipeline requires both source branches to be Succeeded before starting Gold. The notification branch uses Completed after Gold so it can run after either Gold success or failure. Validate this failure-propagation and notification behavior in the deployed factory; a completed notification activity alone does not prove that upstream processing succeeded.

## 12. Audit record identity and retry semantics

**Decision:** Use `(adf_run_id, table_id, stage)` as the audit natural key.

Source-to-Silver and Silver-to-Gold table loops use an idempotent `MERGE ... WITH (HOLDLOCK)` to create or reset the single IN_PROGRESS summary row. Success and failure updates include the stage predicate so a source-stage update cannot alter the Gold-stage record for the same table and parent run.

**Trade-off:** The audit table retains the latest attempt summary for that key, not one row per retry. Detailed attempt-level history remains in ADF execution history. For existing control databases, apply `migrate_audit_log_unique_key.sql` while pipelines are paused. The migration stops if historical duplicate natural keys exist and does not delete or merge audit records automatically.

## 13. Security and data scope

The checked-in data represents a simulated multi-site healthcare network. Patient, clinician, hospital, and laboratory-event records are synthetic; insurance-provider names in the sample feeds are fictional demo entities, and contact values use placeholder `.example` addresses. No real patient information, actual provider relationships, or clinical integrations are included.

The Gold models are operational-analytics examples. The supplied `Normal`, `Abnormal`, and `Critical` statuses are synthetic input categories and are not clinical classifications validated for patient care. The platform must not be used for diagnosis, triage, treatment, or care decisions.

Credentials should be supplied through secure linked-service configuration and Azure Key Vault references, not committed in source control. Any real-world adaptation would require separately designed privacy, access-control, retention, encryption, audit, data-quality, clinical-governance where applicable, and jurisdiction-specific regulatory controls.

## 14. Deployment and operational decisions

- Treat source-table DDL containing DROP statements as a controlled initialization/reset script, not a non-destructive migration.
- Configure environment-specific storage, catalog, schema, notebook, linked-service, and notification references together.
- Preserve the original architecture diagram; update explanatory documentation around it rather than altering the image.
- Run the validation plan and reconcile source, Bronze, Silver, Gold, and audit counts after redeployment.
- Keep the project status accurate: it was successfully executed end-to-end in its original environment, even if cost-saving cleanup means that environment is no longer active.

## 15. Interview discussion prompts

1. Why use metadata-configured ingestion, and which parts of the platform remain code-defined?
2. What guarantees does a timestamp watermark provide, and where can it miss changes?
3. How would you make landing-to-Bronze replay safe?
4. How would you handle late-arriving updates, hard deletes, and equal timestamps?
5. What is the grain of each Gold dataset, and how do the joins preserve it?
6. How would you validate that an ADF master run cannot publish Gold outputs from failed source branches?
7. What evidence would you collect to demonstrate a successful end-to-end run?
