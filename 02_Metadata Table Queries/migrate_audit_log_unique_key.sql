/* =====================================================================
   HealthGrid — Audit key hardening migration
   Target: Azure SQL Database
   Purpose: enforce one audit row per parent ADF run, table, and stage.

   IMPORTANT:
   - Pause ADF triggers and concurrent pipeline runs before applying.
   - Take and verify a database recovery point before applying.
   - This script stops if historical duplicate keys exist.
   - It never deletes, merges, or rewrites audit history automatically.
   - If an index with the expected name exists but has the wrong definition,
     the migration fails for manual review instead of silently accepting it.
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

IF EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID('ctrl.audit_log')
      AND name = 'UQ_audit_log_run_table_stage'
)
AND NOT EXISTS (
    SELECT 1
    FROM sys.indexes i
    WHERE i.object_id = OBJECT_ID('ctrl.audit_log')
      AND i.name = 'UQ_audit_log_run_table_stage'
      AND i.is_unique = 1
      AND i.is_disabled = 0
      AND i.has_filter = 0
      AND (
          SELECT COUNT(*)
          FROM sys.index_columns ic
          WHERE ic.object_id = i.object_id
            AND ic.index_id = i.index_id
            AND ic.key_ordinal > 0
      ) = 3
      AND EXISTS (
          SELECT 1 FROM sys.index_columns ic
          JOIN sys.columns c
            ON c.object_id = ic.object_id AND c.column_id = ic.column_id
          WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id
            AND ic.key_ordinal = 1 AND c.name = 'adf_run_id'
      )
      AND EXISTS (
          SELECT 1 FROM sys.index_columns ic
          JOIN sys.columns c
            ON c.object_id = ic.object_id AND c.column_id = ic.column_id
          WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id
            AND ic.key_ordinal = 2 AND c.name = 'table_id'
      )
      AND EXISTS (
          SELECT 1 FROM sys.index_columns ic
          JOIN sys.columns c
            ON c.object_id = ic.object_id AND c.column_id = ic.column_id
          WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id
            AND ic.key_ordinal = 3 AND c.name = 'stage'
      )
)
    THROW 51012, 'The expected audit index name exists with an incompatible definition. Review the index manually; no index was changed.', 1;
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
