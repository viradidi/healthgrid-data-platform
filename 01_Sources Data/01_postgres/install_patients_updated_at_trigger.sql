/*
    HealthGrid — install/update patients.updated_at trigger

    Non-destructive source migration for an existing PostgreSQL patients table.
    Source timestamps are TIMESTAMP WITHOUT TIME ZONE values and must be stored
    in UTC to match the ADF watermark bounds.
*/

DO $$
BEGIN
    IF to_regclass('public.patients') IS NULL THEN
        RAISE EXCEPTION 'public.patients must exist before installing the watermark trigger';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.set_patients_updated_at_utc()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := timezone('UTC', clock_timestamp());
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_patients_updated_at_utc ON public.patients;

CREATE TRIGGER trg_patients_updated_at_utc
BEFORE UPDATE ON public.patients
FOR EACH ROW
EXECUTE FUNCTION public.set_patients_updated_at_utc();
