# HealthGrid — Deployment and Environment Guide

This guide describes how to restore or redeploy the completed HealthGrid platform in a new Azure environment. The project was originally developed as CareSync and was historically executed end-to-end successfully. Some Azure resources were later decommissioned to control cost; legacy CareSync identifiers remain in exported artifacts.

The original architecture diagram is intentionally preserved. This guide does not require or authorize changes to assets/architecture-overview.png.

## 1. Deployment principles

- Treat the repository as an export of the original implementation, not a ready-to-run infrastructure deployment.
- Provision resources in a disposable development environment first.
- Use synthetic data; do not load real patient information into this educational project.
- Keep credentials, tokens, signed webhook URLs, and connection strings out of Git.
- Align legacy CareSync resource names with the target environment through configuration and deployment-time updates. Do not perform blind global replacements.
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

The exported linked services contain legacy workspace, cluster, and Key Vault references. Recreate or map these to the target environment. Do not assume the original resources still exist.

## 3. Security prerequisite — exposed notification credential

A repository-exported ADF factory configuration contains a Logic Apps request URL with a signed authorization parameter. Treat that URL as a credential because possession of it may permit invoking the workflow.

Before deploying:
1. Revoke or regenerate the exposed Logic Apps trigger authorization URL.
2. Update the ADF global parameter using the newly generated value through a secure deployment process.
3. Remove the credential-bearing value from tracked Git history where appropriate; deleting it from the latest file alone does not invalidate prior clones or history.
4. Review access logs for unexpected invocation.
5. Store the replacement securely. Do not commit the URL, token, or signature.

The repository also contains a recipient address in exported factory configuration. Review whether it should remain public and move environment-specific recipients into deployment configuration.

## 4. Environment configuration matrix

| Setting | Exported implementation | Target environment action |
|---|---|---|
| ADF factory | Legacy name adf-caresync | Choose target name and update references |
| ADF region | centralindia | Select approved region and confirm availability |
| ADF publish branch | adf_publish | Configure repository integration and publish branch |
| ADF environment parameter | DEV | Set target environment explicitly |
| PostgreSQL schema | public | Confirm source schema and table names |
| Control schema | ctrl | Create control objects in target Azure SQL database |
| Storage containers | source, landing | Create containers and grant required access |
| Databricks catalog | adb_caresync | Create/map target catalog; update notebook references consistently |
| Landing Volume | adb_caresync.landing.landing_volume | Create Volume and verify notebook identity access |
| Databricks notebook paths | /caresync-repo/caresync-adb-repo/... | Import notebooks and update ADF paths |
| Databricks compute | Existing cluster ID in export | Select supported target compute; do not reuse old ID |
| Key Vault | Legacy CareSync vault URI | Create/select target vault and grant ADF identity access |
| Notification | Exported Logic Apps global parameter | Create new endpoint and inject securely |
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

- Provision PostgreSQL and create source tables using the source SQL scripts.
- Load intended synthetic source fixtures.
- Provision Azure SQL Database.
- Run 02_Metadata Table Queries/create_control_tables.sql to create ctrl.table_config, ctrl.watermark, ctrl.audit_log, and ctrl.file_ingestion_manifest.
- Verify seeded source and Gold metadata rows.
- Confirm timestamp-watermarked PostgreSQL objects have `ctrl.watermark` rows and inspect the file manifest table for CSV feeds. CSV file selection no longer depends on `ctrl.watermark`.

Review setup scripts before execution; do not run destructive reset/drop scripts against valuable data.

### D2 — Provision ADLS Gen2

- Create source and landing containers.
- Place initial CSV fixtures under configured source folders.
- Create the landing folder structure expected by ADF.
- Configure ADF and Databricks identities with required read/write permissions.
- Confirm the Databricks Volume path maps to intended landing storage.

### D3 — Provision Databricks and Unity Catalog

- Create/select workspace and supported compute.
- Configure Unity Catalog and create target catalog plus bronze, silver, and gold schemas.
- Create the landing Volume used by Landing-to-Bronze.
- Import notebooks from 05_Databricks_Repository/.
- Update legacy notebook paths and catalog references for the target environment.
- Run the calendar preparation notebook and validate its date range.
- Confirm permissions to read landing files and create/replace Delta tables.

The notebooks currently reference legacy adb_caresync catalog and a CareSync landing Volume. Update these references coherently; a partial rename can leave the pipeline writing to and reading from different catalogs.

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

The current implementation advances incremental watermarks to current UTC time, rather than the maximum source timestamp observed. It also uses strict greater-than extraction. Validate late-arriving data, timestamp boundaries, and source clock assumptions before relying on this checkpoint strategy for production completeness.

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
| Audit | Ensure audit updates target intended run/table execution |
| Legacy names | Standardize catalog, workspace, Volume, and notebook references coherently |

## 8. Rollback and recovery

- Pause schedules before repairing a failed deployment.
- Preserve ADF run history, notebook output, audit rows, and checkpoint values.
- Identify the last verified source interval and successful Silver state.
- Do not advance a watermark to make a failed run appear complete.
- For CSV feeds, reconcile the file manifest and original landing path before replay; do not automatically recopy unresolved COPIED/IN_PROGRESS versions.
- For other APPEND, check whether the batch has already been written before replaying.
- For MERGE, confirm source ordering and target state before replaying.
- For FULL, confirm a complete source snapshot before overwriting.
- For Gold, inspect the target after a failed CREATE OR REPLACE operation and rebuild only after confirming input completeness.
- Re-run relevant validation cases and retain evidence.

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
