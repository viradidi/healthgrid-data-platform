/*
   HealthGrid — destructive Azure SQL control-table reset
   Target: the CURRENT Azure SQL database, schema ctrl.

   WARNING: this permanently deletes table_config, watermark, audit_log,
   and file_ingestion_manifest, including all metadata, checkpoints, audit
   history, and file replay state. Use only in a disposable DEV database
   after verifying the server, database, and absence of active ADF runs.

   Explicit opt-in is required on the SAME SQL session:
     EXEC sys.sp_set_session_context
       @key = N'healthgrid_allow_destructive_reset', @value = 1;
   Then execute this script on that same connection. This script never sets
   the confirmation flag itself. Without the opt-in it stops before DDL.
*/

IF ISNULL(TRY_CONVERT(INT, SESSION_CONTEXT(N'healthgrid_allow_destructive_reset')), 0) <> 1
BEGIN
    THROW 51041, 'Destructive reset blocked. Set the explicit session context only after confirming this is a disposable DEV database.', 1;
END;

PRINT CONCAT('HealthGrid control-table reset explicitly authorized for database: ', DB_NAME());

SET XACT_ABORT ON;

BEGIN TRY
    SET XACT_ABORT ON;
    BEGIN TRANSACTION;

    IF OBJECT_ID('ctrl.file_ingestion_manifest', 'U') IS NOT NULL
        DROP TABLE ctrl.file_ingestion_manifest;

    IF OBJECT_ID('ctrl.audit_log', 'U') IS NOT NULL
        DROP TABLE ctrl.audit_log;

    IF OBJECT_ID('ctrl.watermark', 'U') IS NOT NULL
        DROP TABLE ctrl.watermark;

    IF OBJECT_ID('ctrl.table_config', 'U') IS NOT NULL
        DROP TABLE ctrl.table_config;

    COMMIT TRANSACTION;
    EXEC sys.sp_set_session_context @key = N'healthgrid_allow_destructive_reset', @value = NULL;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    EXEC sys.sp_set_session_context @key = N'healthgrid_allow_destructive_reset', @value = NULL;
    THROW;
END CATCH;
