# HealthGrid — Repository Artifact Audit

This is a static review of the committed implementation and documentation. It is not a claim that the current Azure environment has been redeployed or retested.

## Project identity

- Project: HealthGrid; original name: CareSync.
- The project owner confirms the original implementation ran successfully end-to-end. Some Azure resources were later decommissioned to control cost.
- The repository's ADF and Databricks artifacts use HealthGrid naming conventions. Environment-specific endpoints and compute identifiers are represented by placeholders in linked services and must be populated during deployment.
- The original architecture image at assets/architecture-overview.png is protected and must remain unchanged.

## Implementation inventory

| Area | Assets | Purpose |
|---|---|---|
| PostgreSQL | Source DDL and incremental-load SQL | Hospital, doctor, and patient source entities |
| Partner feeds | Initial and incremental CSV fixtures | Laboratory results and insurance providers |
| Control metadata | Control-table DDL, watermark-lookback migration, audit uniqueness migration, and audit SQL | Configuration, bounded PostgreSQL watermarks, per-file manifest, and idempotent run/table/stage audit records |
| Mapping | Silver-to-Gold STTM workbook | Analytical source-to-target mapping |
| ADF | Factory, pipelines, datasets, linked services | Orchestration, metadata lookup, audit, and notifications |
| Databricks ingestion | Landing-to-Bronze notebook | Reads timestamped landing batches into Bronze; schema-drift and same-batch replay guards |
| CSV file manifest | `ctrl.file_ingestion_manifest` and ADF per-file Copy loop | Tracks source file versions through IN_PROGRESS, COPIED, PROCESSED, and FAILED states |
| Databricks transformation | Bronze-to-Silver notebook | Applies configured FULL, APPEND, and version-aware MERGE strategies; validates source/target keys and schema |
| Calendar | Calendar preparation notebook | Reusable date dimension |
| Gold | Patient 360, hospital daily summary, lab test trends notebooks | Dataset-specific analytical transformations |
| Architecture | assets/architecture-overview.png | Original project architecture diagram |

## Metadata-driven design

All layers are metadata-driven. Shared control metadata configures source objects, active status, source and target identifiers, load strategy, watermark information, merge keys, and processing stage.

- Source-to-Silver processing uses active SOURCE_TO_SILVER records in ctrl.table_config.
- Gold orchestration selects active SILVER_TO_GOLD records and resolves notebook paths dynamically using gold_table_name.
- Dataset-specific analytical transformation SQL remains in the corresponding Databricks notebooks.

Metadata drives the end-to-end framework and execution/selection; the individual notebooks implement each dataset's transformation logic.

## Documentation coverage

| Document | Scope |
|---|---|
| README.md | Project overview, architecture, data flow, technology stack, layers, orchestration, and repository guide |
| docs/ENGINEERING_DECISIONS.md | Architecture decisions, trade-offs, assumptions, and interview topics |
| docs/DATA_DICTIONARY.md | Source entities, control metadata, layer responsibilities, and Gold grains |
| docs/OPERATIONS_RUNBOOK.md | Monitoring, audit, checkpoints, troubleshooting, and recovery |
| docs/VALIDATION_PLAN.md | Metadata, ADF, Bronze, Silver, watermark, audit, and Gold test scenarios |
| docs/DEPLOYMENT.md | Environment inventory, secure configuration, deployment, rollback, and cost cleanup |

## Findings and actions

### Notification credential — revoked; repository cleanup applied

The exported ADF factory configuration previously contained a signed Logic Apps trigger URL. The project owner confirms that the URL has been revoked. The latest tracked factory JSON has now been updated to remove the signed URL and replace it with a non-secret deployment placeholder. The recipient value was also replaced with a deployment placeholder.

Revocation addresses credential validity. Repository cleanup addresses accidental redistribution. Historical commits, clones, caches, or forks may still contain the old value; history cleanup can be considered separately, but it is not a substitute for revocation. Inject the newly generated URL and approved recipient through a secure deployment process, never by committing live values.

### Master pipeline dependency semantics

The master pipeline was updated so Gold requires both source branches to be Succeeded. The notification branch intentionally remains dependent on Gold being Completed, allowing notification after either a successful or failed Gold run. Verify these dependency semantics with failure-injection tests after redeployment.

### Replay and checkpoint guarantees

- Landing-to-Bronze appends batches and blocks exact landing-timestamp replay. The CSV branch now tracks file versions through `ctrl.file_ingestion_manifest`; unresolved prior-run IN_PROGRESS/COPIED states require reconciliation. Revised whole-file snapshots can still duplicate rows under APPEND.
- Silver MERGE receives the configured `watermark_column` as its DATE/TIMESTAMP source-version field. It rejects null/duplicate source keys, null source versions, invalid target keys, and schema mismatches; older versions cannot overwrite newer rows, identical equal-version replays are no-ops, and equal-version payload conflicts fail for reconciliation. Runtime data scenarios remain part of the redeployment validation plan.
- PostgreSQL incremental extraction now uses a metadata-configured lookback, a fixed UTC upper bound captured at run start, inclusive/exclusive query boundaries, and monotonic checkpoint advancement after Silver succeeds. The patients row is seeded with a five-minute lookback and its `updated_at` source timestamps are normalized to UTC by the supplied PostgreSQL SQL.
- The lookback reduces short visibility-delay and backdating risk but does not provide CDC or no-loss guarantees. Hard deletes are not captured; changes outside the lookback or changes that fail to update `updated_at` can still be missed. Runtime boundary/concurrency scenarios remain unexecuted until Azure is restored.
- CSV source selection is file-manifest-based, with content MD5 optional.
- Audit rows are unique by `(adf_run_id, table_id, stage)`; source and Gold starts use idempotent HOLDLOCK upserts and finalizers scope updates by stage. Retries update the single summary record; ADF history preserves individual attempt details.
- Existing control databases require `migrate_audit_log_unique_key.sql` for the audit natural key and `add_watermark_lookback.sql` for bounded timestamp overlap. Both migrations are safe to re-run; the watermark migration leaves current checkpoint values unchanged.

### Gold publication and recovery

Gold notebooks use full rebuild/replace behavior. Validate target consistency and recovery if a notebook fails during publication. Test parallel execution for shared-resource conflicts.

### Legacy identifiers and destructive setup

- Create the `healthgrid` Unity Catalog catalog and landing Volume, and import notebooks under `/Shared/HealthGrid/` before running ADF. Populate each linked-service placeholder with the target environment's endpoints and compute identifiers. Treat drop/reset SQL as disposable-environment setup, not as a production migration.

### CI/CD

Two GitHub Actions workflows now exist:

- `.github/workflows/healthgrid-validation.yml` runs automatic repository checks. Its path filters include SQL, CSV, XLSX, documentation, notebooks, JSON, Python, and architecture assets so those changes trigger validation.
- `.github/workflows/healthgrid-azure-integration.yml` is manually triggered, requires an explicit confirmation, and runs behind the `healthgrid-integration` GitHub Environment. Once configured with Azure OIDC and a disposable DEV factory, it starts and monitors the ADF `PL_MASTER` pipeline, which invokes the configured Databricks activities.

The repository-validation workflow has passed after the workflow and artifact updates. These checks remain static. The Azure integration workflow is a provisioned capability only; it has not been executed because the original Azure resources were decommissioned. A future successful ADF run must still be accompanied by activity-level review, Databricks output inspection, audit/watermark checks, and data reconciliation.

## Architecture preservation

Keep the original image file assets/architecture-overview.png unchanged and retain the README embed:

![HealthGrid Data Platform Architecture](assets/architecture-overview.png)

## Conclusion

HealthGrid has a substantial end-to-end implementation footprint and dedicated engineering, data dictionary, operations, validation, and deployment documentation. The project owner confirms historical successful execution. Remaining actions concern security hygiene, deployment portability, and stronger operational guarantees—not whether the original project was completed.
