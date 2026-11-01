# HealthGrid — Operations Runbook

This runbook covers routine execution, monitoring, failure diagnosis, and recovery for the HealthGrid data platform. The project was originally named CareSync, so exported ADF and Databricks artifacts retain legacy identifiers such as `adb_caresync` and `/caresync-repo/caresync-adb-repo/`. Verify these against the target workspace during redeployment.

The project was historically executed end-to-end successfully. This guide is an operational reference for a restored or redeployed environment; it does not claim that a currently available Azure workspace has been revalidated.

## 1. Execution flow

The ADF master pipeline, `PL_MASTER`, coordinates:

1. PostgreSQL source-to-Silver ingestion.
2. ADLS CSV source-to-Silver ingestion.
3. Metadata-driven Silver-to-Gold execution.
4. Email notification.

The source branches use `PL_SOURCE_TO_SILVER_MAIN` and the parameterized `PL_SOURCE_TO_SILVER_INNER`. The inner pipeline reads the selected `ctrl.table_config` row, retrieves a timestamp watermark for non-FULL PostgreSQL loads or consults the per-file manifest for ADLS CSV, then copies data to a timestamped landing folder, and invokes the shared Landing-to-Bronze and Bronze-to-Silver notebooks. PostgreSQL extraction now resolves both schema and table names from metadata. The ADLS CSV branch enumerates files, checks `ctrl.file_ingestion_manifest`, and copies unprocessed file versions individually. Landing folder names use a 24-hour timestamp with milliseconds and the ADF run ID to reduce collisions. Landing-to-Bronze now returns an explicit `DATA` or `NO_DATA` result. An unexpected empty FULL batch fails before Silver can overwrite its target; a FULL CSV feed with files already marked PROCESSED is a successful no-op. Empty incremental batches skip Silver writes and checkpoint advancement, then record a successful zero-row outcome.

Gold orchestration reads active `SILVER_TO_GOLD` rows from `ctrl.table_config` and dynamically resolves each notebook from `gold_table_name`. All layers are metadata-driven; dataset-specific transformation logic resides in the corresponding Databricks notebooks.

## 2. Pre-run checklist

Before triggering a run:

- Confirm PostgreSQL and ADLS sources are reachable and expected input files exist.
- Verify ADF linked services, Key Vault references, ADLS containers, landing paths, Databricks access, Unity Catalog volumes, and target schemas.
- Confirm active source and Gold rows in `ctrl.table_config`.
- Confirm timestamp-watermarked PostgreSQL objects have a `ctrl.watermark` row.
- Confirm `ctrl.file_ingestion_manifest` exists and inspect unresolved CSV file states before running ADLS feeds.
- Review recent `ctrl.audit_log` records for failed or unfinished runs.
- Check that no overlapping run is processing the same source or rebuilding the same Gold target.
- Verify notebook paths and catalog/volume names in the target environment.

The notebook currently uses `/Volumes/adb_caresync/landing/landing_volume`; ADF paths also contain CareSync. These are environment-specific legacy references and must be checked rather than assumed to exist after workspace recreation.

Useful queries:

```sql
SELECT table_id, source_system, source_table_name,
       bronze_table_name, silver_table_name, gold_table_name,
       load_type, watermark_column, merge_keys, stage, is_active
FROM ctrl.table_config
WHERE is_active = 1
ORDER BY stage, source_system, table_id;

SELECT c.table_id, c.source_system, c.source_table_name,
       c.load_type, c.watermark_column, w.watermark_value,
       w.last_updated_timestamp
FROM ctrl.table_config AS c
LEFT JOIN ctrl.watermark AS w ON c.table_id = w.table_id
WHERE c.is_active = 1 AND c.load_type IN ('APPEND','MERGE');

SELECT TOP (100) *
FROM ctrl.audit_log
ORDER BY created_timestamp DESC;

SELECT file_manifest_id, table_id, source_path, source_file_name,
       source_last_modified, source_file_size, source_content_md5,
       status, adf_run_id, landing_path, last_error, updated_timestamp
FROM ctrl.file_ingestion_manifest
WHERE status <> 'PROCESSED'
ORDER BY updated_timestamp DESC;
```

## 3. Normal run procedure

1. Trigger `PL_MASTER` in ADF and record its run ID.
2. Monitor PostgreSQL and ADLS source branches independently.
3. Inspect each child pipeline and table-level ForEach iteration.
4. Confirm Copy activities and Databricks notebooks succeeded.
5. Review audit records for every expected source object.
6. Verify Silver outputs before accepting the Gold stage.
7. Inspect each Gold notebook result and validate the resulting tables.
8. Review notification outcome and record exceptions.

**Orchestration gate:** the master pipeline now starts Silver-to-Gold only when both source branches have `Succeeded`. The email notification remains dependent on Gold being `Completed`, so notification can still run after a Gold success or failure. A successful parent run and table-level audit/data checks are still required before accepting outputs.

## 4. Monitoring and audit interpretation

| Signal | Meaning | Operator response |
|---|---|---|
| ADF activity status | Execution result for a pipeline/activity | Inspect child activities and detailed errors |
| IN_PROGRESS audit row | A table-stage execution was started | Check run age and corresponding ADF activity |
| SUCCESS audit row | Success update activity completed | Validate data and business rules |
| FAILED audit row | Failure handler recorded a failed activity | Inspect original error and recovery point |
| Databricks notebook output | Notebook result, often processed row count | Reconcile against target data |

The audit table uses `(adf_run_id, table_id, stage)` as its natural key: one record per configured object and stage in a parent ADF run. Source and Gold ForEach loops upsert `IN_PROGRESS` with `MERGE ... WITH (HOLDLOCK)`, so a retry reinitializes the same run-stage record. Success/failure updates include the stage predicate. This is a latest-attempt summary for that parent run, not an attempt-by-attempt event history. Retain ADF activity output, Databricks run output, source/target counts, and checkpoint evidence as supporting records.

## 5. Load strategies and watermark handling

### FULL
The source is extracted without a watermark predicate. Silver uses overwrite mode for the selected batch. Confirm the source extraction is complete before execution; a FULL retry can replace the target.

### APPEND
For the ADLS CSV lab-results feed, the file manifest selects new file versions and Silver appends the corresponding batch. `reported_at` is a business event-time field, not the ADF file-selection checkpoint. Exact processed file versions are skipped, but a changed whole-file snapshot is a new version and can reappend rows that existed in the prior version. The feed should be immutable/additive or have a row-level deduplication policy.

### MERGE
For the PostgreSQL patients source, the timestamp watermark selects changes and configured merge keys identify target rows. The current patient configuration uses `updated_at` and `patient_id`; ADF passes the metadata `watermark_column` into the Silver notebook as its source-version field.

Before mutation, the notebook rejects null or duplicate source keys, null source versions, null/duplicate target keys, null target versions, and source/target schema mismatches. Matched rows update only when the incoming version is newer. Older versions are skipped and counted. Equal-version rows with unchanged business values are no-ops; equal-version rows with changed business values fail.

**Recovery:** Do not bypass a failed MERGE validation by deleting or deduplicating rows automatically. Inspect the source batch and target rows for the reported keys, identify the authoritative source version, correct/reconcile the underlying records, and rerun the affected table through the normal pipeline. If the target contains duplicate keys or schema drift, use a reviewed repair or migration before restarting. The ADF watermark should not be advanced manually until the corrected batch has reached Silver.

### Checkpoint caution
For timestamp-watermarked PostgreSQL sources, the exported inner pipeline advances the watermark to `SYSUTCDATETIME()` after the Bronze-to-Silver notebook succeeds. It does not calculate the maximum source timestamp actually observed in the batch. Source extraction uses a strict greater-than predicate. ADLS CSV feeds do not use `ctrl.watermark`; their selection state is stored in `ctrl.file_ingestion_manifest`.

Before manually advancing or repairing a checkpoint, establish:
- The last complete source interval.
- Whether source timestamps are UTC or local.
- Whether late or backdated updates can arrive.
- Whether timestamp precision and serialization are consistent.
- Whether records can fall exactly on the checkpoint boundary.
- Whether the corresponding batch has reached Silver.

Do not move a checkpoint forward simply to clear a failure. If the correct boundary is uncertain, pause scheduling and plan a controlled backfill.

## 5A. CSV file manifest operations

The ADLS CSV branch uses `ctrl.file_ingestion_manifest`; PostgreSQL timestamp-watermarked objects continue to use `ctrl.watermark`.

Normal file lifecycle:

1. ADF enumerates direct child items under the configured source folder and retains `.csv` files.
2. It captures file size, last-modified timestamp, and content MD5 when available.
3. A manifest lookup skips an exact version already marked `PROCESSED`.
4. An unprocessed version is recorded as `IN_PROGRESS`, copied to the run's landing folder, and marked `COPIED`.
5. After Bronze-to-Silver succeeds, the parent table/run marks those copied versions `PROCESSED`.

A previous-run `COPIED` or `IN_PROGRESS` version blocks automatic recopy. This is intentional: the prior run may have committed Bronze or Silver even though final manifest status was not written. Check its `landing_path`, Bronze `landing_timestamp`, Silver target, ADF activity output, and watermark before recovery. A failed Copy version is retryable only after checking for partial target files.

For a clean deployment, the first run processes every eligible CSV file because the new manifest starts empty. When enabling the manifest against populated Bronze/Silver targets, baseline previously processed source versions before scheduling to avoid replaying history. See [File Ingestion Manifest](FILE_INGESTION_MANIFEST.md) for the state machine and recovery checklist.

## 6. Failure diagnosis

### Source connection or authentication
Inspect the failing linked service and activity. Verify network/firewall access, source availability, credentials, Key Vault references, and permissions. Never place credentials in logs or repository files. Rerun only after connectivity is confirmed.

### Missing files or landing path
Inspect the List Source CSV Files Get Metadata activity, configured source folder, Filter output, manifest lookup, sink folder, generated landing timestamp, and notebook parameters. If the source folder exists but contains no eligible CSV files, the ForEach has zero iterations; a FULL CSV run fails the explicit inventory check, while an incremental run reaches `NO_DATA`. If CSV files exist but all versions are already `PROCESSED`, the FULL CSV run is a successful no-op and does not overwrite Silver. If a new file is copied but parses to zero records, the notebook fails closed for FULL. If the source folder is missing or inaccessible, Get Metadata fails and must be treated as a path/permission problem, not an empty feed. PostgreSQL Copy returning zero rows is handled by the explicit no-data notebook path. Do not manually relabel a failed source activity as an empty successful batch.

### Landing-to-Bronze failure
Check source system, table name, landing timestamp, file format, landing contents, volume access, and Bronze permissions. Reconcile Bronze rows for that timestamp before retrying. The notebook compares incoming field names and data types with the existing Bronze table and fails closed on schema drift; apply a reviewed schema migration before retrying. It also blocks appending a landing timestamp already present in Bronze. For CSV feeds, inspect manifest rows: `IN_PROGRESS` means copy outcome is uncertain, `COPIED` means the file is in landing but downstream processing is not finalized, `FAILED` means the Copy failed, and `PROCESSED` means Bronze-to-Silver completed. A prior-run `IN_PROGRESS` or `COPIED` state blocks automatic recopy; use the stored `landing_path` to reconcile the original batch.

### Bronze-to-Silver failure
Check the selected Bronze batch, target schema, configured load type, and merge keys. For MERGE, inspect null and duplicate keys. Determine whether the Silver write committed before a later activity failed. Reconcile the target before retrying.

### Watermark or audit update failure
The success-audit activity runs only after file-manifest finalization and the watermark-control activity succeed. Audit rows are unique by parent run, table, and stage; the upsert resets an existing row to IN_PROGRESS on retry, and status updates are stage-scoped. For PostgreSQL, if data was written but the watermark update failed, the success audit is not written; the parent failure handler should mark the table run FAILED. For CSV, inspect COPIED/PROCESSED manifest rows and the original landing batch before retrying. Inspect the target and processed interval before any checkpoint or manifest repair. APPEND replay may duplicate rows; MERGE replay may overwrite newer values if source ordering is not controlled. If the audit update itself fails after the checkpoint succeeds, validate data and checkpoint before repairing audit metadata.

### Gold notebook failure
Identify the failed Gold metadata row and notebook path. Confirm required Silver inputs, catalog/schema permissions, and target state. Gold notebooks use `CREATE OR REPLACE TABLE`; inspect the target after a failed rebuild rather than assuming the prior output remains intact. Rerun only after confirming the full-rebuild behavior is acceptable.

## 7. Controlled rerun and backfill

1. Pause overlapping or scheduled executions for the affected table.
2. Record the ADF run ID, table ID, landing timestamp, watermark, manifest state, and audit state.
3. Identify the last fully processed batch and whether Bronze/Silver writes committed.
4. Preserve landing files and execution logs.
5. Select the smallest safe recovery scope.
6. For CSV APPEND, inspect the file manifest first. A prior-run `COPIED` or `IN_PROGRESS` file must be reconciled at its original landing path; do not reset it or recopy until Bronze/Silver commit state is known. For other APPEND replay, check for duplicate batch rows before replay.
7. For MERGE, validate key uniqueness and source-version ordering.
8. For FULL, confirm the source extraction is complete before overwriting.
9. Change a watermark only after verifying the recovery boundary.
10. Run the affected stage, reconcile data, then restart downstream processing.
11. Rebuild impacted Gold outputs after Silver is validated.
12. Record recovery actions, counts, checkpoint decisions, and evidence.

Do not delete Bronze or Silver data as a first response. Preserve evidence until the cause and recovery boundary are understood.

## 8. Gold data-quality checks

Run checks appropriate to each output grain:

```sql
-- Patient 360: one intended row per patient
SELECT patient_id, COUNT(*) AS row_count
FROM adb_caresync.gold.patient_360
GROUP BY patient_id
HAVING COUNT(*) > 1;

-- Hospital daily summary: one row per hospital/date
SELECT hospital_id, summary_date, COUNT(*) AS row_count
FROM adb_caresync.gold.hospital_daily_summary
GROUP BY hospital_id, summary_date
HAVING COUNT(*) > 1;

-- Lab trends: one row per test/month
SELECT test_name, year, month, COUNT(*) AS row_count
FROM adb_caresync.gold.lab_test_trends
GROUP BY test_name, year, month
HAVING COUNT(*) > 1;
```

Also reconcile patient lab aggregates, hospital daily totals, and monthly test totals to Silver laboratory results. Confirm abnormal/critical counts do not exceed total tests and rates are within 0–100% when denominators are non-zero. Validate calendar enrichment and expected patient population coverage.

## 9. Known limitations and operational safeguards

- **Audit identity:** one row is retained per `(adf_run_id, table_id, stage)`. Retries reset that row to IN_PROGRESS; the design does not preserve a separate history row for every retry attempt. Use ADF run/activity history for attempt-level detail.
- **Audit migration:** on an existing control database, pause pipelines and run `migrate_audit_log_unique_key.sql`. It fails safely if duplicate natural keys already exist; reconcile duplicates manually and rerun. Do not delete audit history automatically.
- **Master dependencies:** Gold requires both source branches to be Succeeded. The notification branch intentionally uses Completed after Gold so it can report either outcome. Validate this behavior in the deployed factory with failure-injection tests.
- **Watermark calculation:** checkpoint uses current UTC time rather than the maximum source timestamp processed. Test late arrivals and source clock differences.
- **Strict watermark predicate:** equal-timestamp changes and precision boundaries need explicit handling.
- **CSV manifest:** exact file versions are tracked by table, source path/name, last-modified time, size, and optional content MD5. Only `PROCESSED` versions are skipped; unresolved prior-run `IN_PROGRESS`/`COPIED` versions fail closed for manual reconciliation. This is a conservative recovery gate, not a distributed exactly-once transaction.
- **CSV file replacement:** a changed file version is treated as a new delivery. APPEND can duplicate rows if a partner overwrites a whole file; current feed semantics should remain immutable/additive or require row-level deduplication.
- **Manifest scale:** ADF Get Metadata child-item output is limited to 4 MB; partition large source directories or adopt storage inventory/event-driven ingestion when necessary.
- **APPEND replay:** PostgreSQL/other APPEND replay and changed CSV versions still require a defined row-level deduplication or replacement policy.
- **MERGE source uniqueness:** validate one source row per key and deterministic ordering.
- **No CDC contract:** hard deletes and late-arriving updates need separate policies.
- **Gold rebuilds:** Gold notebooks replace their targets rather than incrementally merging changes.
- **No-data handling:** empty FULL batches fail before Silver overwrite; empty incremental batches skip Silver and checkpoint updates and are recorded as successful with zero rows when the Copy activity completes and the notebook can inspect the resulting landing path. ADF Copy no-file errors that fail the Copy activity occur before the notebook and still need a separate source-branch handling decision and runtime test.
- **Schema evolution:** the current Landing-to-Bronze policy rejects field additions, removals, or data-type changes against an existing Bronze table. This is intentional fail-closed behavior; schema changes require a reviewed migration and updated validation evidence.
- **Landing batch identity:** folders use a 24-hour timestamp with milliseconds plus the parent ADF run ID. This reduces accidental path collisions but does not provide cross-run data deduplication.
- **Parallel processing:** ForEach activities run in parallel. Check for duplicate target configurations and shared-resource conflicts.
- **Legacy identifiers:** verify CareSync catalog, volume, and notebook paths in the restored workspace.
- **Destructive source setup:** the PostgreSQL source creation script drops existing source tables. Treat it as a disposable environment reset, not a production migration.
- **Synthetic data:** this is an educational dataset. Real healthcare deployment requires formal privacy, access-control, retention, audit, and regulatory controls.

## 10. Incident record

Record the incident reference, environment, ADF parent/child run IDs, source object or Gold target, metadata table_id, failure timestamp, exact error, last verified checkpoint, affected data interval, recovery action, reconciliation evidence, and final status.

## 11. Operational acceptance criteria

A run is ready for acceptance when:
- Every expected active source configuration has a verified outcome.
- Upstream failures have not been hidden by parent pipeline completion.
- No unexpected IN_PROGRESS audit rows remain.
- Watermarks match the verified processed interval.
- Bronze and Silver batches reconcile to expected inputs.
- Gold outputs pass grain and business-metric checks.
- Run IDs, counts, exceptions, and recovery decisions are recorded.

A green pipeline status is useful evidence, but reconciliation and business-level validation are the acceptance criteria.
