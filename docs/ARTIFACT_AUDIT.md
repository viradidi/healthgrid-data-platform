# HealthGrid — Repository Artifact Audit

This is a static review of the committed implementation and documentation. It is not a claim that the current Azure environment has been redeployed or retested.

## Project identity

- Project: HealthGrid; original name: CareSync.
- The project owner confirms the original implementation ran successfully end-to-end. Some Azure resources were later decommissioned to control cost.
- Remaining CareSync identifiers are legacy deployment names and must be aligned consistently when provisioning a new environment.
- The original architecture image at assets/architecture-overview.png is protected and must remain unchanged.

## Implementation inventory

| Area | Assets | Purpose |
|---|---|---|
| PostgreSQL | Source DDL and incremental-load SQL | Hospital, doctor, and patient source entities |
| Partner feeds | Initial and incremental CSV fixtures | Laboratory results and insurance providers |
| Control metadata | Control-table DDL and audit SQL | Configuration, watermarks, and audit records |
| Mapping | Silver-to-Gold STTM workbook | Analytical source-to-target mapping |
| ADF | Factory, pipelines, datasets, linked services | Orchestration, metadata lookup, audit, and notifications |
| Databricks ingestion | Landing-to-Bronze notebook | Reads timestamped landing batches into Bronze |
| Databricks transformation | Bronze-to-Silver notebook | Applies configured FULL, APPEND, and MERGE strategies |
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

The master pipeline uses Completed dependencies between source branches and the Gold branch. Validate that a failed required source branch cannot lead to Gold being accepted as a successful end-to-end result. Consider explicit Succeeded dependencies or a dedicated quality gate.

### Replay and checkpoint guarantees

- Landing-to-Bronze appends batches; replay can duplicate records without batch-level deduplication or a defined replay policy.
- Silver MERGE validates configured key-column presence, but duplicate source keys and out-of-order versions require explicit tests and handling.
- Incremental checkpoint behavior and strict timestamp boundaries need tests for late arrivals, equality at the checkpoint, timezone consistency, and failure recovery.
- Confirm audit updates distinguish retries and multiple attempts within a parent ADF run.

### Gold publication and recovery

Gold notebooks use full rebuild/replace behavior. Validate target consistency and recovery if a notebook fails during publication. Test parallel execution for shared-resource conflicts.

### Legacy identifiers and destructive setup

Map CareSync catalog, Volume, workspace, and notebook path references to one target naming convention during redeployment. Do not use blind global replacements. Treat drop/reset SQL as disposable-environment setup, not as a production migration.

### CI/CD

A GitHub Actions workflow now exists at .github/workflows/healthgrid-validation.yml. It validates JSON syntax, notebook code-cell syntax, Python syntax, required documentation files, the exact README architecture-image embed, and selected high-confidence credential patterns.

The workflow was committed as a repository change, but its first GitHub Actions run has not yet been independently verified in this audit. Do not claim the checks are passing until the run completes successfully. These static checks do not execute ADF pipelines or Databricks workloads.

## Architecture preservation

Keep the original image file assets/architecture-overview.png unchanged and retain the README embed:

![HealthGrid Data Platform Architecture](assets/architecture-overview.png)

## Conclusion

HealthGrid has a substantial end-to-end implementation footprint and dedicated engineering, data dictionary, operations, validation, and deployment documentation. The project owner confirms historical successful execution. Remaining actions concern security hygiene, deployment portability, and stronger operational guarantees—not whether the original project was completed.
