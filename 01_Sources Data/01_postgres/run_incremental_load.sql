/* =====================================================================
   HealthGrid — PostgreSQL incremental fixture, round 1
   Target: PostgreSQL, schema public.

   One-time synthetic change set. The transaction/advisory lock and marker
   guard prevent duplicate inserts or repeated additive updates on replay.
   Run after create_source_tables.sql. Do not use as a production feed loader.
   ===================================================================== */

BEGIN;
SET LOCAL search_path TO public;
SELECT pg_advisory_xact_lock(hashtext('healthgrid:incremental-fixture:round-1'));

DO $healthgrid_round1_guard$
BEGIN
    IF to_regclass('public.hospitals') IS NULL
       OR to_regclass('public.doctors') IS NULL
       OR to_regclass('public.patients') IS NULL THEN
        RAISE EXCEPTION 'HealthGrid source tables are missing; run the fresh source initializer first.';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.hospitals
        WHERE hospital_name = 'Riverside Specialty Hospital'
          AND city = 'Nashville'
          AND state = 'TN'
    ) THEN
        RAISE EXCEPTION 'HealthGrid incremental fixture round 1 was already applied; no rows were changed.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.hospitals WHERE hospital_id = 1)
       OR NOT EXISTS (SELECT 1 FROM public.doctors WHERE doctor_id = 1)
       OR NOT EXISTS (SELECT 1 FROM public.patients WHERE patient_id = 1)
       OR NOT EXISTS (SELECT 1 FROM public.patients WHERE patient_id = 2500) THEN
        RAISE EXCEPTION 'Expected baseline hospital, doctor, and patient IDs are missing; reconcile the source baseline before applying this fixture.';
    END IF;
END;
$healthgrid_round1_guard$;

/* ---------------------------------------------------------------------
   1. Insert a new hospital and its doctors
   --------------------------------------------------------------------- */
WITH new_hospital AS (
    INSERT INTO hospitals (
        hospital_name,
        city,
        state,
        hospital_type,
        bed_count,
        created_at,
        updated_at
    )
    VALUES (
        'Riverside Specialty Hospital',
        'Nashville',
        'TN',
        'Specialty',
        220,
        timezone('UTC', CURRENT_TIMESTAMP),
        timezone('UTC', CURRENT_TIMESTAMP)
    )
    RETURNING hospital_id
)
INSERT INTO doctors (
    first_name,
    last_name,
    specialty,
    hospital_id,
    phone_number,
    created_at,
    updated_at
)
SELECT
    doctor.first_name,
    doctor.last_name,
    doctor.specialty,
    new_hospital.hospital_id,
    doctor.phone_number,
    timezone('UTC', CURRENT_TIMESTAMP),
    timezone('UTC', CURRENT_TIMESTAMP)
FROM new_hospital
CROSS JOIN (VALUES
    ('Sophia', 'Mitchell', 'Cardiology', '555-9001'),
    ('Liam', 'Turner', 'Neurology', '555-9002')
) AS doctor(first_name, last_name, specialty, phone_number);

/* ---------------------------------------------------------------------
   2. Update existing hospitals and doctors
   --------------------------------------------------------------------- */
UPDATE hospitals
SET
    bed_count = bed_count + 25,
    hospital_type = 'Regional',
    updated_at = timezone('UTC', CURRENT_TIMESTAMP)
WHERE hospital_id = 1;

UPDATE doctors
SET
    specialty = 'Emergency Medicine',
    phone_number = '555-0101',
    updated_at = timezone('UTC', CURRENT_TIMESTAMP)
WHERE doctor_id = 1;

/* ---------------------------------------------------------------------
   3. Insert new patients
   --------------------------------------------------------------------- */
INSERT INTO patients (
    first_name,
    last_name,
    date_of_birth,
    gender,
    city,
    state,
    registered_hospital_id,
    created_at,
    updated_at
)
VALUES
    (
        'Ava',
        'Bennett',
        DATE '1988-04-17',
        'F',
        'Austin',
        'TX',
        1,
        timezone('UTC', CURRENT_TIMESTAMP),
        timezone('UTC', CURRENT_TIMESTAMP)
    ),
    (
        'Noah',
        'Carter',
        DATE '1976-11-03',
        'M',
        'Dallas',
        'TX',
        2,
        timezone('UTC', CURRENT_TIMESTAMP),
        timezone('UTC', CURRENT_TIMESTAMP)
    ),
    (
        'Mia',
        'Reed',
        DATE '1995-08-29',
        'F',
        'Denver',
        'CO',
        7,
        timezone('UTC', CURRENT_TIMESTAMP),
        timezone('UTC', CURRENT_TIMESTAMP)
    );

/* ---------------------------------------------------------------------
    4. Update existing patients
   --------------------------------------------------------------------- */
UPDATE patients
SET
    city = 'Houston',
    state = 'TX',
    registered_hospital_id = 3,
    updated_at = timezone('UTC', CURRENT_TIMESTAMP)
WHERE patient_id = 1;

UPDATE patients
SET
    first_name = 'Elena',
    city = 'Seattle',
    state = 'WA',
    registered_hospital_id = 8,
    updated_at = timezone('UTC', CURRENT_TIMESTAMP)
WHERE patient_id = 2500;

COMMIT;
