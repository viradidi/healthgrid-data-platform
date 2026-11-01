/* =====================================================================
   HealthGrid — Audit key hardening migration
   Target: Azure SQL Database
   Purpose: enforce one audit row per parent ADF run, table, and stage.

   IMPORTANT:
   - Take a database backup before applying this migration.
   - This script intentionally stops if historical duplicate keys exist.
   - It does not delete or merge audit history automatically.
   - Review and reconcile duplicates before rerunning this migration.
   ===================================================================== */

IF OBJECT_ID('ctrl.audit_log', 'U') IS NULL
    THROW 51010, 'ctrl.audit_log does not exist. Run the control-table setup first.', 1;
GO

IF EXISTS (
    SELECT 1
    FROM ctrl.audit_log
    GROUP BY adf_run_id, table_id, stage
    HAVING COUNT(*) > 1
)
    THROW 51011, 'Duplicate audit keys exist. Reconcile duplicate (adf_run_id, table_id, stage) rows before adding the unique key.', 1;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID('ctrl.audit_log')
      AND name = 'UQ_audit_log_run_table_stage'
)
BEGIN
    CREATE UNIQUE INDEX UQ_audit_log_run_table_stage
        ON ctrl.audit_log (adf_run_id, table_id, stage);
END;
GO
