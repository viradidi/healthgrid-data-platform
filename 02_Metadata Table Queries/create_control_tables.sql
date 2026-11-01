/* =====================================================================
   CareSync Health Network — Control/Metadata Framework
   Target: Azure SQL Database
   Creates the ctrl schema + control/metadata tables, then seeds table_config
   with the 5 source objects (3 Postgres tables + 2 ADLS CSV files)
   and initial watermark rows for the incremental ones.
   ===================================================================== */

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'ctrl')
BEGIN
    EXEC('CREATE SCHEMA ctrl');
END
GO

/* ---------------------------------------------------------------------
   1. ctrl.table_config — one row per source table/file, drives every
      stage (SOURCE_TO_SILVER, SILVER_TO_GOLD)
   To recreate from scratch, run drop_control_tables.sql first.
   --------------------------------------------------------------------- */
CREATE TABLE ctrl.table_config (
    table_id             INT IDENTITY(1,1) PRIMARY KEY,
    source_system        VARCHAR(50)   NOT NULL,   -- e.g. neon_postgres, adls_csv
    source_schema_name   VARCHAR(100)  NULL,        -- SQL sources only
    source_table_name    VARCHAR(200)  NULL,        -- table name, or logical file name for CSV;
                                                     -- NULL for gold-stage rows (no single source)
    source_file_format   VARCHAR(20)   NULL,        -- e.g. csv
    source_path          VARCHAR(500)  NULL,        -- ADLS container/path, CSV sources only
    bronze_table_name    VARCHAR(200)  NULL,        -- NULL for gold-stage rows
    silver_table_name    VARCHAR(200)  NULL,        -- NULL for gold-stage rows
    gold_table_name      VARCHAR(200)  NULL,
    load_type            VARCHAR(20)   NOT NULL CHECK (load_type IN ('FULL','APPEND','MERGE')),
    watermark_column     VARCHAR(100)  NULL,        -- timestamp extraction field for timestamp-watermarked sources; ADLS CSV uses the file manifest
    merge_keys           VARCHAR(200)  NULL,        -- comma-separated business key(s); required only when load_type = MERGE
    stage                VARCHAR(20)   NOT NULL CHECK (stage IN ('SOURCE_TO_SILVER','SILVER_TO_GOLD')),
    is_active             BIT           NOT NULL DEFAULT 1,
    created_timestamp    DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_timestamp    DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

/* ---------------------------------------------------------------------
   2. ctrl.watermark — last processed watermark value per table_id
   --------------------------------------------------------------------- */
CREATE TABLE ctrl.watermark (
    table_id               INT           NOT NULL PRIMARY KEY
                                          REFERENCES ctrl.table_config (table_id),
    watermark_value        VARCHAR(200)  NULL,
    last_updated_timestamp DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

/* ---------------------------------------------------------------------
   3. ctrl.audit_log — one row per table, per run, per stage
   --------------------------------------------------------------------- */
CREATE TABLE ctrl.audit_log (
    audit_id           INT IDENTITY(1,1) PRIMARY KEY,
    adf_run_id         VARCHAR(100)  NOT NULL,
    table_id           INT           NOT NULL REFERENCES ctrl.table_config (table_id),
    stage              VARCHAR(20)   NOT NULL CHECK (stage IN ('SOURCE_TO_SILVER','SILVER_TO_GOLD')),
    status             VARCHAR(20)   NOT NULL CHECK (status IN ('SUCCESS','FAILED','IN_PROGRESS')),
    records_written    INT           NULL,
    start_time         DATETIME2     NULL,
    end_time           DATETIME2     NULL,
    created_timestamp  DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

/* ---------------------------------------------------------------------
   4. ctrl.file_ingestion_manifest — one source-file version per metadata
      object. A file is considered ingested only after its copied batch has
      completed Bronze and Silver processing.
   --------------------------------------------------------------------- */
CREATE TABLE ctrl.file_ingestion_manifest (
    file_manifest_id       BIGINT IDENTITY(1,1) PRIMARY KEY,
    table_id               INT           NOT NULL REFERENCES ctrl.table_config (table_id),
    source_path            NVARCHAR(500) NOT NULL,
    source_file_name       NVARCHAR(260) NOT NULL,
    source_last_modified   DATETIME2(7)  NOT NULL,
    source_file_size       BIGINT        NOT NULL CHECK (source_file_size >= 0),
    source_content_md5     NVARCHAR(64)  NOT NULL DEFAULT N'',
    status                 VARCHAR(20)   NOT NULL
                           CHECK (status IN ('IN_PROGRESS','COPIED','PROCESSED','FAILED')),
    adf_run_id             VARCHAR(100)  NOT NULL,
    landing_path           NVARCHAR(1000) NULL,
    last_error             NVARCHAR(2000) NULL,
    discovered_timestamp   DATETIME2(7)  NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_timestamp      DATETIME2(7)  NOT NULL DEFAULT SYSUTCDATETIME(),
    processed_timestamp    DATETIME2(7)  NULL,
    CONSTRAINT UQ_file_ingestion_manifest_identity UNIQUE
    (
        table_id,
        source_path,
        source_file_name,
        source_last_modified,
        source_file_size,
        source_content_md5
    )
);
GO

CREATE INDEX IX_file_ingestion_manifest_status
    ON ctrl.file_ingestion_manifest (table_id, status, adf_run_id);
GO

/* =====================================================================
   Seed data — ctrl.table_config
   3 Postgres tables (internal) + 2 ADLS CSV files (external partners)
   All rows are stage = SOURCE_TO_SILVER; SILVER_TO_GOLD rows will be
   added once the gold layer tables are designed.
   ===================================================================== */

INSERT INTO ctrl.table_config
    (source_system, source_schema_name, source_table_name, source_file_format, source_path,
     bronze_table_name, silver_table_name, gold_table_name,
     load_type, watermark_column, merge_keys, stage, is_active)
VALUES
    -- Internal hospital system (Neon Postgres)
    ('neon_postgres', 'public', 'hospitals', NULL, NULL,
     'hospitals', 'hospitals', NULL,
     'FULL', NULL, NULL, 'SOURCE_TO_SILVER', 1),

    ('neon_postgres', 'public', 'doctors', NULL, NULL,
     'doctors', 'doctors', NULL,
     'FULL', NULL, NULL, 'SOURCE_TO_SILVER', 1),

    ('neon_postgres', 'public', 'patients', NULL, NULL,
     'patients', 'patients', NULL,
     'MERGE', 'updated_at', 'patient_id', 'SOURCE_TO_SILVER', 1),

    -- External partner feeds (ADLS CSV)
    ('adls_csv', NULL, 'lab_results', 'csv', 'lab_results',
     'lab_results', 'lab_results', NULL,
     'APPEND', NULL, NULL, 'SOURCE_TO_SILVER', 1),

    ('adls_csv', NULL, 'insurance_providers', 'csv', 'insurance_providers',
     'insurance_providers', 'insurance_providers', NULL,
     'FULL', NULL, NULL, 'SOURCE_TO_SILVER', 1);
GO

/* =====================================================================
   Seed data — ctrl.watermark
   Initial timestamp watermark for PostgreSQL incremental objects (patients).
   ADLS CSV file selection is controlled by ctrl.file_ingestion_manifest.
   ===================================================================== */

INSERT INTO ctrl.watermark (table_id, watermark_value, last_updated_timestamp)
SELECT table_id, '1900-01-01T00:00:00', SYSUTCDATETIME()
FROM ctrl.table_config
WHERE source_system = 'neon_postgres'
  AND load_type IN ('APPEND', 'MERGE');
GO


/* =====================================================================
   Seed data — ctrl.table_config (gold layer)
   3 analytics/reporting tables, each built by joining/aggregating multiple
   silver tables — no single source table, so source_table_name,
   bronze_table_name and silver_table_name are all NULL; the join/aggregation
   target selection and execution are driven by metadata; dataset-specific
   transformation logic remains in the corresponding Gold notebooks.
   Full rebuild every run (load_type = FULL), no watermark/merge keys.
   ===================================================================== */

INSERT INTO ctrl.table_config
    (source_system, source_schema_name, source_table_name, source_file_format, source_path,
     bronze_table_name, silver_table_name, gold_table_name,
     load_type, watermark_column, merge_keys, stage, is_active)
VALUES
    ('silver', NULL, NULL, NULL, NULL,
     NULL, NULL, 'patient_360',
     'FULL', NULL, NULL, 'SILVER_TO_GOLD', 1),

    ('silver', NULL, NULL, NULL, NULL,
     NULL, NULL, 'hospital_daily_summary',
     'FULL', NULL, NULL, 'SILVER_TO_GOLD', 1),

    ('silver', NULL, NULL, NULL, NULL,
     NULL, NULL, 'lab_test_trends',
     'FULL', NULL, NULL, 'SILVER_TO_GOLD', 1);
GO

