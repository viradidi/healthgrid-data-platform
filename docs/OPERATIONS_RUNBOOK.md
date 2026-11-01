# HealthGrid — Operations Runbook

This runbook covers routine execution, monitoring, failure diagnosis, and recovery for the HealthGrid data platform. The project was originally named CareSync, so exported ADF and Databricks artifacts retain legacy identifiers such as `adb_caresync` and `/caresync-repo/caresync-adb-repo/`. Verify these against the target workspace during redeployment.

The project was historically executed end-to-end successfully. This guide is an operational reference for a restored or redeployed environment; it does not claim that a currently available Azure workspace has been revalidated.

## 1. Execution flow

The ADF master pipeline, `PL_MASTER`, coordinates:

1. PostgreSQL source-to-Silver ingestion.
2. ADLS CSV source-to-Silver ingestion.
3. Metadata-driven Silver-to-Gold execution.
4. Email notification.

The source branches use `PL_SOURCE_TO_SILVER_MAIN` and the parameterized `PL_SOURCE_TO_SILVER_INNER`. The inner pipeline reads the selected `ctrl.table_config` row, retrieves a watermark for APPEND/MERGE loads, copies data to a timestamped ADLS landing folder, and invokes the shared Landing-to-Bronze and Bronze-to-Silver notebooks.

Gold orchestration reads active `SILVER_TO_GOLD` rows from `ctrl.table_config` and dynamically resolves each notebook from `gold_table_name`. All layers are metadata-driven; dataset-specific transformation logic resides in the corresponding Databricks notebooks.

## 2. Pre-run checklist

Before triggering a run:

- Confirm PostgreSQL and ADLS sources are reachable and expected input files exist.
- Verify ADF linked services, Key Vault references, ADLS containers, landing paths, Databricks access, Unity Catalog volumes, and target schemas.
- Confirm active source and Gold rows in `ctrl.table_config`.
- Confirm each APPEND/MERGE source has a `ctrl.watermark` row.
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

The audit table is not a complete event log. Retain ADF activity output, Databricks run output, source/target counts, and checkpoint evidence as supporting records.

## 5. Load strategies and watermark handling

### FULL
The source is extracted without a watermark predicate. Silver uses overwrite mode for the selected batch. Confirm the source extraction is complete before execution; a FULL retry can replace the target.

### APPEND
The source watermark selects new data and Silver appends the batch. The current lab-results configuration uses `reported_at`. Replaying a previously written batch can duplicate rows because the append path does not inherently deduplicate by batch identity.

### MERGE
The watermark selects changes and configured merge keys identify target rows. The current patient configuration uses `updated_at` and `patient_id`. Validate that the incoming batch has one deterministic row per merge key. The current notebook updates matched rows without comparing source-version timestamps to target versions.

### Checkpoint caution
The exported inner pipeline advances the watermark to `SYSUTCDATETIME()` after the Bronze-to-Silver notebook succeeds. It does not calculate the maximum source timestamp actually observed in the batch. Source extraction uses a strict greater-than predicate.

Before manually advancing or repairing a checkpoint, establish:
- The last complete source interval.
- Whether source timestamps are UTC or local.
- Whether late or backdated updates can arrive.
- Whether timestamp precision and serialization are consistent.
- Whether records can fall exactly on the checkpoint boundary.
- Whether the corresponding batch has reached Silver.

Do not move a checkpoint forward simply to clear a failure. If the correct boundary is uncertain, pause scheduling and plan a controlled backfill.

## 6. Failure diagnosis

### Source connection or authentication
Inspect the failing linked service and activity. Verify network/firewall access, source availability, credentials, Key Vault references, and permissions. Never place credentials in logs or repository files. Rerun only after connectivity is confirmed.

### Missing files or landing path
Inspect the Copy activity, source folder, sink folder, generated landing timestamp, and notebook parameters. Confirm the expected files exist. The Landing-to-Bronze notebook exits when the timestamped path is missing; do not interpret that exit alone as a valid empty batch. Never proceed with a FULL Silver overwrite until the intended batch is verified.

### Landing-to-Bronze failure
Check source system, table name, landing timestamp, file format, landing contents, volume access, and Bronze permissions. Reconcile Bronze rows for that timestamp before retrying. The notebook appends to Bronze, so replaying a batch already written can duplicate it.

### Bronze-to-Silver failure
Check the selected Bronze batch, target schema, configured load type, and merge keys. For MERGE, inspect null and duplicate keys. Determine whether the Silver write committed before a later activity failed. Reconcile the target before retrying.

### Watermark or audit update failure
Watermark update and success-audit update are separate activities after the Bronze-to-Silver notebook. If data was written but the watermark was not advanced, inspect the target and processed interval before retrying. APPEND replay may duplicate rows; MERGE replay may overwrite newer values if source ordering is not controlled. If the watermark advanced but audit update failed, validate data and checkpoint before repairing audit metadata.

### Gold notebook failure
Identify the failed Gold metadata row and notebook path. Confirm required Silver inputs, catalog/schema permissions, and target state. Gold notebooks use `CREATE OR REPLACE TABLE`; inspect the target after a failed rebuild rather than assuming the prior output remains intact. Rerun only after confirming the full-rebuild behavior is acceptable.

## 7. Controlled rerun and backfill

1. Pause overlapping or scheduled executions for the affected table.
2. Record the ADF run ID, table ID, landing timestamp, watermark, and audit state.
3. Identify the last fully processed batch and whether Bronze/Silver writes committed.
4. Preserve landing files and execution logs.
5. Select the smallest safe recovery scope.
6. For APPEND, check for duplicate batch rows before replay.
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

- **Master dependencies:** Gold is triggered after source branches are Completed, not explicitly Succeeded. Validate upstream outcomes; consider changing dependencies to Succeeded after reviewing failure propagation.
- **Watermark calculation:** checkpoint uses current UTC time rather than the maximum source timestamp processed. Test late arrivals and source clock differences.
- **Strict watermark predicate:** equal-timestamp changes and precision boundaries need explicit handling.
- **APPEND replay:** landing and Silver append paths are not inherently deduplicated by batch identity.
- **MERGE source uniqueness:** validate one source row per key and deterministic ordering.
- **No CDC contract:** hard deletes and late-arriving updates need separate policies.
- **Gold rebuilds:** Gold notebooks replace their targets rather than incrementally merging changes.
- **No-file handling:** confirm missing landing paths cannot lead to an unintended empty-batch overwrite.
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
