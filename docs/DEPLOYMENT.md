# HealthGrid — Deployment and Environment Guide

This guide describes how to restore or redeploy the completed HealthGrid platform in a new Azure environment. The project was originally developed as CareSync and was successfully executed end-to-end in its original Azure environment. Some cloud resources were later decommissioned to control cost. The repository now uses HealthGrid naming conventions; Azure endpoints, database/user values, workspace URL, and cluster ID in linked-service exports are deployment placeholders that must be supplied for a restored environment.

The original architecture diagram is intentionally preserved. This guide does not require or authorize changes to assets/architecture-overview.png.

## 1. Deployment principles

- Treat the repository as an export of the original implementation, not a ready-to-run infrastructure deployment.
- Provision resources in a disposable development environment first.
- Use synthetic data; do not load real patient information into this educational project.
- Keep credentials, tokens, signed webhook URLs, and connection strings out of Git.
- Replace the explicit linked-service placeholders with values from the target Azure environment. The `healthgrid` catalog and `/Shared/HealthGrid/` notebook paths are the repository's canonical names; change them only when updating notebooks, ADF references, and documentation together.
- Validate the complete path from source extraction to Gold output before enabling schedules.
- Use VALIDATION_PLAN.md as the deployment acceptance specification.

## 2. Azure resources and configuration inventory

| Component | Purpose | Configuration to verify |
|---|---|---|
| Azure Data Factory | Master and child pipeline orchestration | Factory name, region, Git integration, publish branch, global parameters |
| Azure SQL Database | Metadata, watermark, and audit control tables | Server/database, firewall, schema permissions, linked service |
| PostgreSQL source | Hospitals, doctors, and patients | Host, database, schema, credentials, network access |
| ADLS Gen2 | Partner files and timestamped landing data | Storage account, containers, folder paths, permissions |
| Azure Databricks | Bronze, Silver, Gold processing | Workspace URL, compute policy/cluster, runtime, permissions |
| Unity Catalog | Catalogs, schemas, tables, and landing Volume | Catalog/schema names, Volume path, grants |
| Azure Key Vault | Secret storage for linked services | Vault URI, secret names, managed identity access |
| Logic Apps endpoint | Pipeline status notification | New endpoint URL stored securely; request schema and authorization |

Before enabling the notification endpoint, implement/inspect the Logic Apps workflow against [the committed ADF producer contract](NOTIFICATION_CONTRACT.md). Confirm the root fields, empty `status_table` handling, legacy recipient key, authorization, receiver-side run-ID deduplication, and actual email action. The Logic Apps workflow definition is not included in this repository; a static ADF validation cannot certify the external consumer schema or mailbox delivery.

The linked-service JSON files contain deployment placeholders for Key Vault, ADLS Gen2, Azure SQL, the Databricks workspace, and the Databricks cluster. Populate each value for the target environment before publishing; do not assume the original cloud resources still exist.

## 3. Security prerequisite — exposed notification credential

A repository-exported ADF factory configuration contains a Logic Apps request URL with a signed authorization parameter. Treat that URL as a credential because possession of it may permit invoking the workflow.

Before deploying:
1. Revoke or regenerate the exposed Logic Apps trigger authorization URL.
2. Update the ADF global parameter using the newly generated value through a secure deployment process.
3. Remove the credential-bearing value from tracked Git history where appropriate; deleting it from the latest file alone does not invalidate prior clones or history.
4. Review access logs for unexpected invocation.
5. Store the replacement securely. Do not commit the URL, token, or signature.
6. Confirm the `PL_SEND_EMAIL` request is accepted by the Logic Apps trigger using the exact contract in `docs/NOTIFICATION_CONTRACT.md`; test both populated and empty audit arrays.

The repository also contains a recipient address in exported factory configuration. Review whether it should remain public and move environment-specific recipients into deployment configuration.

## 4. Environment configuration matrix

| Setting | Exported implementation | Target environment action |
|---|---|---|
| ADF factory | `adf-healthgrid` | Confirm the deployed factory name and linked-service references |
| ADF region | centralindia | Select approved region and confirm availability |
| ADF publish branch | adf_publish | Configure repository integration and publish branch |
| ADF environment parameter | DEV | Set target environment explicitly |
| PostgreSQL schema | public | Confirm source schema and table names |
| Control schema | ctrl | Create control objects in target Azure SQL database |
| Storage containers | source, landing | Create containers and grant required access |
| Databricks catalog | `healthgrid` | Create the catalog and required schemas before running notebooks |
| Landing Volume | `healthgrid.landing.landing_volume` | Create the Volume and verify notebook identity access |
| Databricks notebook paths | `/Shared/HealthGrid/...` | Import notebooks to these workspace paths or update ADF references consistently |
| Databricks compute | `<existing-cluster-id>` placeholder | Select supported target compute and replace the placeholder |
| Key Vault | `https://<key-vault-name>.vault.azure.net/` | Set the target vault URL and grant ADF identity access |
| Linked-service endpoints | Explicit placeholders in linked-service JSON | Populate ADLS account, Azure SQL server/database/username, and Databricks workspace URL before publishing |
| Notification | Exported Logic Apps global parameter | Create a new endpoint and inject it securely |
| Email recipient | Exported factory parameter | Configure approved recipient securely |

## 5. Deployment sequence

### D0 — Secure and prepare

- Rotate the exposed Logic Apps authorization URL as described above.
- Review repository history for credentials, connection strings, tokens, and other secrets.
- Decide target Azure region, naming convention, resource group, and environment.
- Establish budget alerts and auto-shutdown/cluster termination policies.
- Use synthetic data only.

**Exit gate:** no known live credential remains exposed in repository or deployment configuration.

### D1 — Provision source and control services

- Provision a new disposable PostgreSQL source database for the synthetic fixtures. Run `01_Sources Data/01_postgres/create_source_tables.sql` for a fresh source. It creates and seeds `public.hospitals`, `public.doctors`, and `public.patients` only when none already exists; it contains no table-drop operation and fails closed when any target table exists.
- Load only the intended synthetic source fixtures. Do not use the initial create script as a refresh operation.
- Apply the two PostgreSQL incremental fixture scripts only once, in the documented round-1 then round-2 sequence, after reviewing the [Source Fixture Contract](SOURCE_FIXTURE_CONTRACT.md). Each script now fails on replay and verifies its baseline prerequisites.
- Upload the initial and later CSV fixtures as separate file versions. The lab-results later file is a 20-row APPEND delivery; the later insurance-provider file is a complete 30-row FULL snapshot, not a five-row delta.
- For an existing PostgreSQL `patients` table, run `01_Sources Data/01_postgres/install_patients_updated_at_trigger.sql`; this migration replaces the trigger definition without dropping patient rows.
- Verify the PostgreSQL `trg_patients_updated_at_utc` trigger exists and updates `patients.updated_at` when a patient row changes without an explicit timestamp assignment.
- Provision Azure SQL Database. Run `02_Metadata Table Queries/create_control_tables.sql` only for a fresh control database. It creates and seeds the four control tables, refuses to run when any target table already exists, and uses a session gate across its GO-separated batches so later statements remain blocked when the preflight fails.
- For an existing control database, do not rerun the fresh initializer. Run `02_Metadata Table Queries/add_watermark_lookback.sql` after the control tables exist. It adds `watermark_lookback_minutes` and initializes the existing PostgreSQL patients configuration to five minutes only when the column is first introduced; it does not modify existing `ctrl.watermark` checkpoints.
- For an existing control database, pause ADF triggers and concurrent runs, verify a database recovery point, then run `02_Metadata Table Queries/migrate_audit_log_unique_key.sql`. It stops on duplicate natural keys and also rejects an existing same-name index with an incompatible definition; it never deletes or merges audit history.
- Verify seeded source and Gold metadata rows. Confirm timestamp-watermarked PostgreSQL objects have `ctrl.watermark` rows and inspect the file manifest table for CSV feeds. CSV file selection no longer depends on `ctrl.watermark`.

**Destructive reset is a separate, explicit operation — not part of deployment or migration.** Only use the reset scripts against a disposable DEV database after verifying the server, database, schema, and that no ADF run is active:
- PostgreSQL: connect to the intended source database, execute `SET healthgrid.allow_destructive_reset = 'true';` on that connection, then run `01_Sources Data/01_postgres/reset_source_tables.sql` using the same connection. The script consumes the setting with `RESET` before dropping only the three named `public` tables.
- Azure SQL: connect to the intended control database, execute `EXEC sys.sp_set_session_context @key = N'healthgrid_allow_destructive_reset', @value = 1;` on that session, then run `02_Metadata Table Queries/drop_control_tables.sql` in that same session. The script clears the confirmation context and wraps child-first drops in a transaction with rollback on error. It deletes metadata, watermarks, audit history, and CSV manifest state.

Never run either reset script against an environment whose data or control state must be retained. A reset is not a substitute for the release rollback and recovery procedure in Section 8.

### D2 — Provision ADLS Gen2

- Create source and landing containers.
- Place initial CSV fixtures under configured source folders.
- Create the landing folder structure expected by ADF.
- Configure ADF and Databricks identities with required read/write permissions.
- Confirm the Databricks Volume path maps to intended landing storage.

### D3 — Provision Databricks and Unity Catalog

- Create/select workspace and supported compute.
- Configure Unity Catalog and create catalog `healthgrid` with `landing`, `bronze`, `silver`, and `gold` schemas.
- Create the `healthgrid.landing.landing_volume` Volume used by Landing-to-Bronze.
- Import notebooks from 05_Databricks_Repository/.
- Confirm notebooks are imported under `/Shared/HealthGrid/` and that their `healthgrid` catalog references match the target Unity Catalog setup.
- Run the calendar preparation notebook and validate its date range.
- Confirm permissions to read landing files and create/replace Delta tables.

The notebooks use the `healthgrid` catalog and `healthgrid.landing.landing_volume`. Create these Unity Catalog objects before execution; if you choose different names, update all notebooks, ADF paths, and deployment settings consistently.

### D4 — Configure Key Vault and linked services

- Create/select target Key Vault.
- Add required secrets using new credentials.
- Grant ADF managed identity permission to read only required secrets.
- Configure Key Vault linked service to the target vault.
- Configure PostgreSQL, Azure SQL, ADLS Gen2, and Databricks linked services.
- Configure Databricks authentication through a supported secure mechanism.
- Verify linked-service connection tests.

Never put secret values directly in linked-service JSON, pipeline parameters, notebook source, or Git.

### D5 — Import and configure ADF assets

Import factory, datasets, linked services, and pipelines from 04_Azure Data Factory Repository/.

Review and update:
- Factory and global parameters.
- Linked-service references and dataset connection parameters.
- Source and landing container names.
- PostgreSQL source schema and table references.
- Databricks workspace and compute settings.
- Notebook paths for Landing-to-Bronze, Bronze-to-Silver, and all Gold notebooks.
- Key Vault references and secret names.
- Logic Apps notification configuration and recipient.
- Trigger and schedule settings.

Keep the metadata-driven pattern intact: source-to-Silver processing is configured from active SOURCE_TO_SILVER rows in ctrl.table_config; Gold orchestration selects active SILVER_TO_GOLD rows and resolves notebook paths from gold_table_name. Dataset-specific analytical transformations remain in their Databricks notebooks.

Before publishing, review the [ADF Source Extraction Contract](ADF_SOURCE_EXTRACTION_CONTRACT.md). Confirm that source dispatch accepts only the two configured source systems, both source lookups are scoped to active SOURCE_TO_SILVER metadata, inner table_id is numeric, PostgreSQL incremental watermark rows are valid, and the Copy query resolves the intended schema/table and half-open timestamp interval. Validate these expression paths in a disposable factory before enabling schedules.

### D6 — Validate one source object at a time

1. Test each linked service.
2. Run one PostgreSQL FULL object and reconcile source, landing, Bronze, and Silver.
3. Run patient MERGE with controlled insert and update fixtures.
4. Run one CSV APPEND object and validate the selected file batch.
5. Run the CSV FULL object.
6. Inspect audit and watermark changes after each run.

Do not enable parallel execution or schedules until individual paths are validated.

### D7 — Validate Gold and orchestration

- Confirm the three active Gold metadata rows.
- Verify dynamic notebook path resolution for each Gold target.
- Run each Gold notebook and validate grain and metrics against independent SQL aggregations.
- Run PL_MASTER only after source branches pass individually.
- Confirm source branch failures cannot be mistaken for successful upstream processing merely because activity status is Completed.
- Verify audit status and notification behavior.
- Execute critical recovery, duplicate replay, and watermark boundary tests.

### D8 — Production-like readiness and scheduling

Only after D0–D7 pass:
- Configure approved schedules and concurrency limits.
- Set alerts for pipeline failures, stale IN_PROGRESS audit rows, and unexpected row-count changes.
- Establish checkpoint repair and backfill ownership.
- Capture deployment version, ADF run IDs, test evidence, and sign-off.
- Recheck budget alerts, cluster auto-termination, and storage lifecycle settings.

## 6. First-run and subsequent-run procedure

### First run

1. Confirm source fixtures and metadata.
2. Confirm incremental watermarks are initialized to the intended starting boundary.
3. Run source pipelines and inspect every object-level result.
4. Verify Bronze batch timestamps and Silver target counts.
5. Execute calendar preparation if not already provisioned.
6. Run Gold and validate all three datasets.
7. Retain run IDs, counts, checkpoint values, and test evidence.

### Subsequent incremental runs

1. Review current watermarks and recent audit history.
2. Confirm new source rows/files meet the extraction predicate.
3. Trigger the relevant source pipeline.
4. Verify the batch reaches Silver before accepting checkpoint advancement.
5. Reconcile changed data and inspect audit records.
6. Run Gold only after required source datasets have succeeded.
7. Record exceptions and controlled replay/backfill.

The PostgreSQL patients load now uses a fixed UTC upper bound captured at the start of the table run and a metadata-configured five-minute lookback. The query uses an inclusive lower boundary and exclusive upper boundary; after Silver succeeds, the checkpoint advances to the captured upper bound through a monotonic update. The lookback can still miss changes that arrive or are backdated more than five minutes, does not capture deletes, and depends on `updated_at` being maintained in UTC. Validate the bounded-window, concurrency, and late-arrival cases in `docs/VALIDATION_PLAN.md` before relying on this pattern for production completeness.

## 7. Deployment-specific technical checks

| Area | Required check |
|---|---|
| Source schema | Confirm source tables and watermark columns match metadata |
| Metadata | Confirm active table IDs, load types, keys, and stages |
| Landing paths | Confirm ADF output paths match Databricks Volume paths |
| CSV manifest | Verify per-file metadata identity, status lifecycle, bootstrap, and recovery of COPIED/IN_PROGRESS rows |
| Bronze replay | Test duplicate behavior before retrying an already-landed batch |
| Silver MERGE | Test duplicate/null keys and out-of-order updates |
| Watermarks | Confirm checkpoint advancement and failure recovery |
| Master pipeline | Gate Gold on successful source processing, not only Completed |
| Gold metadata | Confirm active targets resolve to valid notebook paths |
| Gold rebuild | Confirm CREATE OR REPLACE behavior and recovery after failure |
| Parallelism | Validate ForEach concurrency and prevent overlapping writes |
| Audit | Verify one unique row per parent run/table/stage, idempotent start upserts, and stage-scoped status updates |
| Deployment placeholders | Confirm all linked-service endpoints, workspace URL, cluster ID, database, and username are populated for the target environment |

## 8. Release rollback and data recovery

Rollback is not one transaction. Restoring an earlier Git commit or ADF definition does **not** undo writes already made to Delta tables, reverse Azure SQL migrations, or restore watermark and file-manifest state. Treat code rollback, data recovery, and control-state repair as separate operations.

### 8.1 Capture a pre-change recovery baseline

Before publishing ADF changes, importing notebooks, changing metadata, or running a destructive FULL load:

1. Record the repository commit SHA, release/change identifier, target environment, and the currently published ADF version. Preserve the deployed factory/pipeline export without secrets; the collaboration-branch commit alone does not prove what is currently published.
2. Pause scheduled triggers and confirm no overlapping parent run is active for the affected tables.
3. Export the active `ctrl.table_config` rows and capture all relevant `ctrl.watermark` values, unresolved manifest rows (`IN_PROGRESS`, `COPIED`, or `FAILED`), recent audit records, and ADF parent/activity run IDs.
4. Capture the current Bronze/Silver/Gold table names, schemas, row counts, and Delta table versions/history where available. Preserve the source snapshot or exact CSV file versions needed to reproduce the affected batch.
5. Verify the Azure SQL recovery/backup configuration and retention window, and verify whether the required Delta table versions are still retained. A Git export or notebook copy is not a data backup.
6. For a control-schema migration, take and verify the database recovery point before applying it. The audit unique-key migration already documents this prerequisite; apply the same discipline to other control changes.

Do not start a release if the recovery method for a table that may be overwritten or appended is unknown.

### 8.2 Choose the rollback method by change type

| Changed area | Preferred rollback/recovery | Important boundary |
|---|---|---|
| ADF factory/pipeline definitions | Restore the last known-good definitions from a recorded commit/export and publish them through the same ADF publishing process. Verify the deployed factory after publishing. | Reverting Git alone does not change the live published factory. The manual Azure integration workflow starts `PL_MASTER`; it is not a deployment or rollback workflow. |
| Databricks notebooks | Restore the notebook files from the known-good commit and re-import/redeploy them to the exact workspace paths referenced by ADF. Verify the deployed notebook contents/version before restarting triggers. | Restoring notebook code does not reverse any table writes made by the failed release. |
| Azure SQL control schema | Prefer a forward corrective migration for an additive schema change. If database recovery is required, restore to a separate database using the configured point-in-time/backup capability, validate metadata and state, then deliberately reconnect the environment. | There are no automatic down migrations. Restoring the control database also rewinds metadata, watermarks, audit rows, and manifest states; those must be reconciled with the actual lake contents before cutover. |
| Bronze/Silver FULL | Rebuild from a verified complete source snapshot or restore a retained Delta table version when its history/files are still available and the restore is validated. | FULL replaces the current target. Do not assume the prior table contents can be reconstructed from the new target alone. |
| Silver APPEND | Identify the exact landing batch and determine whether it was written before replay. Remove or restore data only with a reviewed, batch-scoped recovery procedure. | Blind replay can duplicate business rows; the file manifest is not a distributed transaction with Delta. |
| Silver MERGE | Reprocess only after confirming business keys, source versions, and payloads; otherwise restore/rebuild the affected table from a verified state. | Version-aware MERGE makes matching replays safer, but it does not correct an incorrect transformation or recover hard deletes automatically. |
| Gold CREATE OR REPLACE | After restoring the intended notebook version, rebuild from verified Silver inputs; use a retained Delta version only when it is still available and validated. | Gold outputs are full rebuilds. Re-running a failed notebook without checking the Silver inputs and published code is not a rollback. |
| Watermarks and CSV manifest | Reconcile the checkpoint and each file state against the actual landing, Bronze, and Silver results; update control state only after the data outcome is established. | Never advance a watermark to hide a failure, reset a checkpoint blindly, or mark a file PROCESSED merely to clear a blocked run. |

Delta time travel/restore is conditional on the required table history and underlying data files still being retained. Confirm retention and test the restore path in the target environment; do not treat a table version number alone as a guaranteed recovery point.

### 8.3 Controlled recovery sequence

1. Stop new schedules and manual dispatches for the affected pipeline; wait for or cancel active runs deliberately and preserve their run IDs and outputs.
2. Record the failed release commit, deployed ADF version, affected notebook paths, activity error, data batches, audit rows, watermarks, manifest entries, and target table versions.
3. Classify the incident as code/configuration, source/landing, Bronze/Silver data, Gold publication, or control-state failure. Identify whether a write completed before the reported failure.
4. Restore the last known-good ADF and/or notebook definitions when code is implicated. Publish/re-import them and verify the actual deployed artifacts; do not assume a Git revert is sufficient.
5. Recover or rebuild affected data using the method in the table above. Preserve unresolved landing files and manifest evidence until each copied batch has been reconciled.
6. Reconcile control state with the resulting data. A checkpoint may only represent a successfully processed source interval; manifest status may only represent the verified outcome of that file version. Never restore only the control database or only the lake and assume they are consistent.
7. Run the relevant recovery tests in `docs/VALIDATION_PLAN.md`, then reconcile source, landing, Bronze, Silver, Gold, audit, watermark, and manifest outcomes.
8. Re-enable schedules only after the recovery owner records the evidence and approves the release/recovery gate.

A failed activity may occur after an earlier write succeeded. Use activity outputs and actual target state to determine the recovery point; the parent pipeline result alone is not enough to decide whether replay is safe.


## 9. Cost-conscious operation and cleanup

For development:
- Use short-lived or job-scoped compute where practical.
- Enable cluster auto-termination and stop compute after validation.
- Avoid always-on SQL warehouses unless needed.
- Use small synthetic fixtures for routine tests.
- Set budget alerts and review storage/compute usage.
- Remove temporary resources only after capturing required evidence.

Before deleting an environment, preserve repository exports, configuration templates without secrets, test reports, run IDs, and architecture documentation. Decommissioning cloud resources does not invalidate historical successful execution; it means the environment must be provisioned again for new runtime verification.

## 10. Deployment record

| Field | Value |
|---|---|
| Deployment identifier | |
| Environment | |
| Azure region | |
| ADF factory | |
| Azure SQL database | |
| PostgreSQL source | |
| ADLS storage account | |
| Databricks workspace/catalog | |
| Deployment date | |
| Repository commit | |
| ADF master run ID | |
| Validation plan results | |
| Known exceptions | |
| Reviewer/approver | |
| Cleanup/decommission date | |

Do not fill deployment records with assumed resource IDs, dates, run IDs, or test results. Record observed values only.

## 11. Optional GitHub Actions Azure integration workflow

The repository includes `.github/workflows/healthgrid-azure-integration.yml`. It is manual-only and starts the ADF `PL_MASTER` pipeline after an explicit confirmation. The workflow polls the ADF run and returns success only when the run reaches `Succeeded`; it requests cancellation if the monitoring window expires. ADF is responsible for invoking the configured Databricks notebook activities.

Configure the GitHub Environment **`healthgrid-integration`** before using this workflow:

| Environment configuration | Name | Purpose |
|---|---|---|
| Secret | `AZURE_CLIENT_ID` | Microsoft Entra application/client ID |
| Secret | `AZURE_TENANT_ID` | Microsoft Entra tenant ID |
| Secret | `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| Variable | `HEALTHGRID_AZURE_RESOURCE_GROUP` | Resource group containing the target factory |
| Variable | `HEALTHGRID_AZURE_DATA_FACTORY_NAME` | Name of the deployed DEV Data Factory |

Configure workload identity federation on the Microsoft Entra application/service principal with:
- Issuer: `https://token.actions.githubusercontent.com`
- Subject: `repo:viradidi/healthgrid-data-platform:environment:healthgrid-integration`
- Audience: `api://AzureADTokenExchange`

Grant the identity only the permissions needed on the target Data Factory resource. Prefer a custom role over broad subscription or resource-group Contributor access. The custom role should allow factory/pipeline/run reads, `Microsoft.DataFactory/factories/pipelines/createrun/action`, and `Microsoft.DataFactory/factories/pipelineruns/cancel/action`. The cancellation action is used only when this workflow's monitoring window expires. Do not grant permission to edit or publish pipelines for a workflow that only needs to execute and monitor them.

Where available, configure the GitHub Environment with required reviewers so a person reviews the deployment target before Azure authentication. The workflow itself also requires the `confirm_run` input to be checked. Do not change it to run on pushes or pull requests.

**Execution boundary:** `PL_MASTER` runs the active source metadata and downstream Gold processing. It can write to Bronze/Silver/Gold targets and invoke the notification branch. Run it only against a disposable DEV environment containing synthetic data. Before dispatch, verify source connectivity, linked services, secrets, Unity Catalog objects, notebook paths, compute, and metadata configuration.

A successful workflow run proves that the monitored ADF master pipeline reached a successful terminal state. It does not replace the scenario-level tests, activity-output review, audit/watermark inspection, or row-count and Gold-grain reconciliation in `docs/VALIDATION_PLAN.md`.

The original Azure resources were decommissioned after successful project completion to control cost. The integration workflow is therefore committed as a gated capability, not as evidence of a current live Azure test.
