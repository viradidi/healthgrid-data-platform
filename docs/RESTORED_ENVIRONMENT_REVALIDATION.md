# HealthGrid — restored Azure end-to-end revalidation

**Current status: BLOCKED — a restored disposable Azure environment is required.**

The project owner previously confirmed that the original HealthGrid implementation ran successfully end to end. That historical execution remains valid as an owner-confirmed project outcome. It does not prove that the latest committed Gold integrity checks and deployment artifacts have been re-executed against a restored Azure Databricks environment.

The latest repository commit reviewed for this gate is `63a26a74ce0676e3d320cc913fa4523c26b1101e`. GitHub Actions repository validation checks syntax, configuration and static contracts. It does not execute ADF, Spark, Delta Lake or Unity Catalog. The manually triggered Azure integration workflow has been prepared for the live gate.

## Scope of this revalidation

The acceptance run must exercise the complete path:

1. PostgreSQL operational sources and partner CSV files.
2. Azure Data Factory source-to-Silver branches.
3. ADLS landing and Bronze processing.
4. Databricks Silver FULL, APPEND and version-aware MERGE behavior as selected by metadata.
5. Gold orchestration and all three current Gold notebooks:
   - `NB_patient_360`
   - `NB_hospital_daily_summary`
   - `NB_lab_test_trends`
6. Gold output integrity checks, audit updates and final ADF orchestration status.

The three Gold notebooks perform pre-publication input checks and post-publication schema, grain and metric checks. A notebook must complete successfully for its output checks to be considered passed. The Gold outputs are full rebuilds using `CREATE OR REPLACE TABLE`; this revalidation must therefore use a disposable synthetic DEV environment, never production data.

## Required environment preparation

Before triggering the workflow:

- Restore the Azure SQL control database, PostgreSQL source database, ADLS Gen2 storage, Azure Databricks workspace/catalog/Volume and Azure Data Factory.
- Recreate the three Gold metadata rows and all required active source metadata from the repository seed/control scripts.
- Restore the source fixtures and upload the initial/incremental partner CSV files to the paths configured in metadata.
- Apply the repository's control-table migrations in the documented order.
- Import Databricks notebooks to the workspace paths referenced by ADF, including `/Shared/HealthGrid/Gold/`.
- Replace deployment placeholders in linked services and Key Vault references through secure configuration.
- Configure GitHub OIDC federation and the least-privilege Azure role for the `healthgrid-integration` environment.
- Configure the GitHub Environment variables `HEALTHGRID_AZURE_RESOURCE_GROUP` and `HEALTHGRID_AZURE_DATA_FACTORY_NAME`, and secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`.

Use the deployment guide and validation plan for the full setup order. Do not run destructive reset scripts against an existing environment. The full master pipeline can rebuild Gold outputs.

## Acceptance gates

A successful ADF master status by itself is not sufficient. The live run is accepted only when all of the following have been inspected and retained:

| Gate | Required evidence |
|---|---|
| ADF source branches | Both `Source to Silver Postgres` and `Source to Silver ADLS csv` complete with `Succeeded` status. |
| Gold dispatch | `PL_SILVER_TO_GOLD` is actually invoked after both source branches succeed; an empty or skipped Gold branch is not a pass. |
| Gold execution | All three expected Gold notebook activities complete with `Succeeded` status. |
| Gold audit | Three corresponding `SILVER_TO_GOLD` audit rows for the parent ADF run have `SUCCESS` status and non-null `records_written`. |
| Gold data | Each of the three Gold tables exists, has non-zero rows, meets its declared grain, and passes the schema, relationship and metric checks in its notebook. |
| Source progress | PostgreSQL watermarks advance only after successful downstream processing. No expected CSV file remains in an unresolved `IN_PROGRESS`, `COPIED` or `FAILED` state. |
| Reconciliation | Source, landing/Bronze, Silver and Gold counts are reconciled using the documented source-specific semantics. APPEND files are additive event deliveries; the provider CSV is a full snapshot. |
| Run identity | ADF parent/child run IDs, repository commit SHA, execution time and activity-level results are retained together. |

The repository's ADF integration workflow now collects a sanitized activity-level evidence artifact and fails closed when it cannot verify the required source and Gold activity outcomes. It does not export raw activity input/output payloads, which could contain connection or parameter data.

## How to run

1. Restore and inspect the disposable DEV environment.
2. Open **Actions → HealthGrid Azure Integration** in GitHub.
3. Select **Run workflow** and explicitly set `confirm_run=true`.
4. Review the activity-level evidence artifact produced by the run.
5. Query `ctrl.audit_log`, source watermarks and `ctrl.file_ingestion_manifest` for the same parent ADF run.
6. Inspect the three Databricks Gold tables and retain row counts and validation results.
7. Complete the evidence record below only after all gates pass.

## Execution evidence record

| Field | Value |
|---|---|
| Repository commit SHA | Pending live run |
| Execution date/time (UTC) | Not yet recorded |
| Azure Data Factory name | Not yet recorded |
| Parent ADF run ID | Not yet recorded |
| PostgreSQL child pipeline run ID | Not yet recorded |
| ADLS CSV child pipeline run ID | Not yet recorded |
| Silver-to-Gold child pipeline run ID | Not yet recorded |
| Gold table row counts | Not yet recorded |
| Audit/watermark/manifest verification | Not yet recorded |
| Operator acceptance | Pending |

**Do not change this document to PASS based only on GitHub repository validation or the parent ADF terminal status.** Attach sanitized run IDs, table counts and relevant activity outcomes before recording final acceptance.
