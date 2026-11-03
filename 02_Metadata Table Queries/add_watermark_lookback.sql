/*
    HealthGrid — PostgreSQL watermark lookback migration

    Adds a per-source configurable overlap window to ctrl.table_config.
    Existing PostgreSQL patients configuration is initialized to five minutes.
    Other metadata rows retain the zero-minute default.

    Safe to re-run: the column is added and initialized only when it is absent.
    This migration does not change current watermark values.
*/

IF OBJECT_ID('ctrl.table_config', 'U') IS NULL
    THROW 51030, 'ctrl.table_config must exist before applying the watermark lookback migration.', 1;
GO

IF COL_LENGTH('ctrl.table_config', 'watermark_lookback_minutes') IS NULL
BEGIN
    ALTER TABLE ctrl.table_config
    ADD watermark_lookback_minutes INT NOT NULL
        CONSTRAINT DF_table_config_watermark_lookback_minutes DEFAULT (0) WITH VALUES;

    UPDATE ctrl.table_config
    SET watermark_lookback_minutes = 5,
        updated_timestamp = SYSUTCDATETIME()
    WHERE source_system = 'neon_postgres'
      AND source_table_name = 'patients'
      AND stage = 'SOURCE_TO_SILVER'
      AND load_type = 'MERGE';
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID('ctrl.table_config')
      AND name = 'CK_table_config_watermark_lookback_minutes'
)
BEGIN
    ALTER TABLE ctrl.table_config
    ADD CONSTRAINT CK_table_config_watermark_lookback_minutes
        CHECK (watermark_lookback_minutes >= 0);
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.default_constraints dc
    JOIN sys.columns c
      ON c.object_id = dc.parent_object_id
     AND c.column_id = dc.parent_column_id
    WHERE dc.parent_object_id = OBJECT_ID('ctrl.table_config')
      AND c.name = 'watermark_lookback_minutes'
)
BEGIN
    ALTER TABLE ctrl.table_config
    ADD CONSTRAINT DF_table_config_watermark_lookback_minutes
        DEFAULT (0) FOR watermark_lookback_minutes;
END;
GO
