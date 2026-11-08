# HealthGrid — Senior Engineering Readiness Review

**Review date:** 8 November 2026  
**Repository:** [viradidi/healthgrid-data-platform](https://github.com/viradidi/healthgrid-data-platform)  
**Overall status:** Successfully executed end to end in the original Azure environment — project-owner confirmed  
**Latest repository validation:** [GitHub Actions run #289](https://github.com/viradidi/healthgrid-data-platform/actions/runs/41712998524), successful on 3 November 2026

## Executive assessment

HealthGrid is a substantial metadata-driven Azure data platform reference implementation. It integrates PostgreSQL operational tables and partner CSV feeds through Azure Data Factory, ADLS Gen2, Databricks, and Delta Lake. Its strongest engineering characteristics are reusable source-to-Silver and Silver-to-Gold metadata dispatch, per-file manifest replay state, bounded watermark processing, version-aware MERGE semantics, source-success gating, audit/notification contracts, and pre-publication Gold integrity checks.

The project owner confirms that the platform was deployed and executed end to end in its original Azure environment. The environment was later decommissioned to control cost. The repository does not retain the original ADF/Databricks run identifiers, activity outputs, runtime counts, or external notification delivery proof, so this review distinguishes owner-confirmed runtime acceptance from repository inspection.

**Overall portfolio rating: 8.7/10 — strong senior-level data engineering project.** This rating assesses the architecture and implementation evidence available in the repository. It is not a claim of current cloud availability, production certification, clinical readiness, or independent audit.

## Capability assessment

| Competency | Rating | Repository evidence |
|---|---:|---|
| Platform architecture and decomposition | 9.2/10 | ADF orchestration, ADLS landing, Databricks processing, control database, and Bronze/Silver/Gold layers |
| Metadata-driven orchestration | 9.4/10 | Active source and Gold metadata selection, dynamic notebook dispatch, explicit empty-metadata guards |
| Ingestion and replay control | 8.8/10 | PostgreSQL watermark lookback, CSV file-version manifest, timestamped landing batches, and exact-batch replay guards |
| Bronze/Silver transformation design | 9.0/10 | Shared load-strategy framework for FULL, APPEND, and version-aware MERGE with key/schema/type validation |
| Gold analytics and modelling | 8.5/10 | Patient 360, hospital daily summary, and laboratory test trends with documented grain and metric semantics |
| Data quality and integrity | 9.0/10 | Input preflights, relationship/key checks, duplicate laboratory event guard, output grain and metric assertions |
| Operational controls and recovery | 8.6/10 | Run audit, checkpoint protection, manifest states, source-success Gold gate, notification contract, and recovery runbook |
| Testing and delivery | 7.5/10 | Broad static CI contracts and syntax validation; no live ADF/Databricks execution in the repository workflow |

## What makes the project technically strong

### 1. Metadata-driven execution across layers

Active `ctrl.table_config` rows select source objects, load strategies, and Gold output models. The ADF dispatchers validate that active metadata exists before entering their ForEach loops, and Gold notebook paths are resolved from the configured `gold_table_name`. Dataset-specific Gold transformation logic remains in the individual Databricks notebooks, which is a useful separation between orchestration metadata and analytical implementation.

### 2. Deliberate incremental and replay semantics

PostgreSQL incremental extraction uses a captured upper bound and a configured five-minute lookback. The checkpoint advances only after Bronze-to-Silver succeeds, using a monotonic update. CSV feeds use `ctrl.file_ingestion_manifest` to track file versions through `IN_PROGRESS`, `COPIED`, `PROCESSED`, and `FAILED` states. The manifest uses path, name, modification time, size, and content MD5 when available; when MD5 is absent, a replacement preserving the other attributes may not be distinguishable.

### 3. Shared Silver load-strategy framework

The Bronze-to-Silver notebook supports FULL, APPEND, and version-aware MERGE. It validates required metadata, safe identifiers, source and target keys, schema/type compatibility, and source-version behavior. For MERGE, older versions are skipped, identical equal-version replays are no-ops, and conflicting equal-version payloads fail for reconciliation. APPEND remains intentionally non-deduplicating across different landing batches.

### 4. Gold publication safeguards

Three Gold datasets are defined: `patient_360` at patient grain, `hospital_daily_summary` at hospital/date grain, and `lab_test_trends` at test/month grain. Before table replacement, the notebooks validate laboratory event IDs, dimension/calendar uniqueness, required relationships and modeled fields. Output schema, key uniqueness, and metric bounds are checked after materialization. This is a fail-closed publication guard; it does not perform Silver deduplication.

### 5. Failure-aware orchestration and audit

The master pipeline waits for both source branches to complete, evaluates their actual statuses, and starts Gold only when both succeeded. Notification follows the Gold decision, including source-failure paths. Audit records are scoped to the parent ADF run, object, and stage, and start/finalization updates are designed for idempotent retries.

## Remaining engineering limitations

| Area | Current boundary | Senior-level next improvement |
|---|---|---|
| PostgreSQL watermark | The five-minute lookback can miss late or backdated updates older than the configured interval; hard deletes are not captured; `updated_at` must be maintained reliably in UTC. This is not CDC. | Use source CDC/tombstones where available, or document and test a source-specific overlap and reconciliation strategy. |
| CSV APPEND | The manifest protects exact file-version replay, not repeated business events delivered under a different file version. | Add a stable event-key deduplication/reconciliation stage in Silver if the source contract supports it. Keep the current Gold duplicate guard. |
| Gold publication | Gold tables use full `CREATE OR REPLACE TABLE` rebuilds rather than incremental maintenance or historical SCD2 snapshots. | Retain full refresh for the current scope; introduce incremental/partitioned Gold only with measured volume, backfill, and recovery requirements. |
| External notification | ADF sends a documented payload to a Logic Apps endpoint, but the external Logic Apps consumer definition is not included in this repository. The recipient field preserves the legacy spelling `email_receipients` pending consumer compatibility verification. | Validate the real consumer contract and delivery path in a restored environment; version the payload before changing field names. |
| Cloud revalidation | The original Azure resources were decommissioned. The Azure integration workflow is manually gated and needs a disposable environment, OIDC, secrets, and variables. | Restore a budgeted DEV environment only when a new live verification is needed; retain actual ADF and Databricks run outputs. |
| Evidence retention | Historical end-to-end success is owner-confirmed, but detailed ADF/Databricks run IDs, logs, counts, and notification delivery evidence are not attached. | Attach sanitized originals when available; do not fabricate run IDs, row counts, or elapsed times. |
| CI scope | The latest successful run validates repository artefacts and static contracts; it does not run Spark/Delta, ADF, Unity Catalog permissions, or Logic Apps. | Add local Spark tests where feasible and keep cloud integration tests manual/environment-gated. |

## Latest repository validation

[GitHub Actions run #289](https://github.com/viradidi/healthgrid-data-platform/actions/runs/41712998524) completed successfully on 3 November 2026 for commit `1016393d9c4de2d063230f18479d2d1bffbfee7f`.

The workflow log reports validation of 18 JSON files, 3 notebooks, and 3 Python files, as well as extensive static checks for ADF metadata dispatch, control-table safety, SQL initialization/migration guards, file-manifest transitions, Gold model contracts, notebook paths, orchestration gates, required documentation, architecture-image retention, and selected credential patterns.

This is **repository validation**, not a count of unit tests and not live Azure integration evidence. The separate Azure integration workflow is manually triggered and requires a configured disposable DEV environment, GitHub OIDC federation, and environment secrets/variables.

## Responsible-use and data scope

All person-level, hospital, laboratory-event, and partner-provider records are synthetic. The project is not a clinical product, contains no live clinical-system integration, and must not be used for diagnosis, triage, treatment, or patient-care decisions. `Normal`, `Abnormal`, and `Critical` are source-fixture reporting categories, not clinical thresholds.

## Portfolio-ready description

> Designed, deployed, and owner-verified a metadata-driven Azure data platform integrating PostgreSQL operational data and partner CSV feeds through Azure Data Factory, ADLS Gen2, and Databricks/Delta Lake. Implemented metadata-selected ingestion and Gold processing, per-file replay manifests, timestamp-watermark controls, reusable FULL/APPEND/version-aware MERGE transformations, run-scoped audit and notification contracts, source-success orchestration gates, and validated patient, hospital, and laboratory analytics outputs. The original Azure environment was later decommissioned; the repository retains the implementation, deployment exports, architecture, and validation documentation.

Do not describe the project as a live clinical system, CDC-complete platform, production-certified service, independently audited deployment, or continuously available service. Do not claim measured performance, cost savings, or runtime SLAs without retained evidence.

## Final readiness decision

**Portfolio presentation: ready.** The project demonstrates advanced data-engineering patterns and contains substantial implementation documentation. The remaining items are environment-specific operational hardening and evidence retention, not missing core architecture or missing Gold analytics. Preserve the existing original architecture image and keep the synthetic-data and watermark/APPEND limitations visible to reviewers.