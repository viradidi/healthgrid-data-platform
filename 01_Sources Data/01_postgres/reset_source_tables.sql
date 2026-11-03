/*
    HealthGrid — destructive PostgreSQL source reset
    Target: the current PostgreSQL database, schema public.

    WARNING: this permanently drops the HealthGrid patients, doctors, and
    hospitals tables and their data. Use only in a disposable development
    environment after checking the connected server, database, and schema.

    Explicit opt-in is required on the SAME database session:
      SET healthgrid.allow_destructive_reset = 'true';
    Then execute this script on that same connection. The setting is not
    enabled by this script. Without the opt-in, execution stops before DDL.
*/

DO $healthgrid_reset_guard$
BEGIN
    IF current_setting('healthgrid.allow_destructive_reset', true) IS DISTINCT FROM 'true' THEN
        RAISE EXCEPTION
            'Destructive reset blocked. On this same connection, explicitly run SET healthgrid.allow_destructive_reset = ''true'' only after confirming this is a disposable database.';
    END IF;
END;
$healthgrid_reset_guard$;

BEGIN;

DROP TABLE IF EXISTS public.patients;
DROP TABLE IF EXISTS public.doctors;
DROP TABLE IF EXISTS public.hospitals;

COMMIT;
