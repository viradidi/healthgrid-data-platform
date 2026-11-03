# HealthGrid — Source Fixture Contract

## Purpose and execution boundary

The files in `01_Sources Data` are demonstration inputs for the synthetic source systems. They are not a recurring production ingestion mechanism and do not implement CDC. The PostgreSQL incremental SQL files are one-time fixture change sets; the ADLS CSV files represent file deliveries/snapshots that the ADF manifest identifies by file version.

Use a fresh disposable PostgreSQL database and a disposable ADLS test container. Do not rerun the PostgreSQL incremental fixture scripts after they have committed successfully. Each script now takes a transaction-scoped advisory lock and checks a stable marker plus the expected baseline rows before any data changes. A replay fails closed; the inserts and updates are kept within one transaction.

## PostgreSQL source sequence

1. Run `01_Sources Data/01_postgres/create_source_tables.sql` once against an empty database. It creates the 50-hospital, 500-doctor, and 5,000-patient synthetic baseline.
2. Run `01_Sources Data/01_postgres/run_incremental_load.sql` once for round 1. It adds Riverside Specialty Hospital, two doctors, and three patients; it also updates one existing hospital, doctor, and two existing patients.
3. Run `01_Sources Data/01_postgres/run_incremental_load_round_2.sql` once for round 2. It adds Lakeside Community Hospital, two doctors, and three patients; it also updates a second existing hospital, doctor, and two existing patients.

After both rounds, the expected entity counts are:

| Source table | Baseline | Round 1 additions | Round 2 additions | Expected total |
|---|---:|---:|---:|---:|
| `hospitals` | 50 | 1 | 1 | 52 |
| `doctors` | 500 | 2 | 2 | 504 |
| `patients` | 5,000 | 3 | 3 | 5,006 |

The two incremental SQL files are fixture-generation scripts, not an idempotent feed API. Their marker guards prevent accidental re-execution, including a concurrent second invocation of the same round. If a script fails, its transaction must be rolled back; inspect the database and error before attempting any repair. Do not remove marker rows or hospital records merely to make a script run again.

The PostgreSQL patients trigger refreshes `updated_at` in UTC for each UPDATE. The manually supplied timestamp values in the fixture statements are not relied upon as the final values when the trigger fires. The timestamp watermark extracts patient changes; hospitals and doctors are configured as FULL loads.

## ADLS CSV fixture contract

The repository groups sample files under `Initial_laod` (initial fixtures) and `Incremental_load` (later file versions). Upload the files to the storage folders configured for the corresponding metadata objects; the repository folder names are sample organization, not automatically inferred ADF paths.

| Logical source | Initial file | Later file | Configured strategy | Semantics |
|---|---|---|---|---|
| `lab_results` | `lab_results_2026_09_14_1329.csv` | `lab_results_2026_09_14_1440.csv` | APPEND | Initial file contains laboratory event IDs 1–8,228; later file contains 20 new events with IDs 8,229–8,248. It is an additive delivery, not a revised copy of the initial file. |
| `insurance_providers` | `insurance_providers.csv` | `insurance_providers.csv` | FULL | Initial file is a complete 25-provider snapshot (IDs 1–25); later file is a complete 30-provider snapshot (IDs 1–30). The later file replaces the reference snapshot; it is not a five-row delta. |

**Important insurance-provider distinction:** the incremental-folder provider CSV is a full revised snapshot. Keep `load_type = FULL`; do not change it to APPEND. The five additional provider IDs are included alongside the existing provider IDs, and some reference attributes may be revised between snapshots. A FULL run should rebuild Silver from the complete selected snapshot rather than append it to the prior version.

**Important laboratory distinction:** `reported_at` is an event/reporting timestamp inside each row. ADF file selection uses file metadata and `ctrl.file_ingestion_manifest`, not `reported_at` or the PostgreSQL timestamp watermark. The incremental file uses new event IDs and is intended to append.

The patient fixture updates in round 2 reference insurance provider IDs 3, 8, 14, and 21, which remain present in the 30-row later provider snapshot. The lab fixtures reference patient IDs 1–5,000, hospital IDs 1–50, and doctor IDs 1–500 from the baseline source.

## Replay and validation rules

- PostgreSQL fixture scripts are one-time changesets; replay must fail before any additive insert or update.
- The initial and incremental lab CSVs must have unique, non-overlapping, contiguous IDs covering 1–8,248 when considered together.
- Provider snapshot IDs must be unique and cover exactly 1–25 initially and 1–30 in the later full snapshot.
- Every lab record's patient, hospital, and doctor reference must fall within the seeded baseline identifier ranges.
- Provider names and contact values are synthetic demo values; contact emails use the reserved `.example` domain.
- ADF's file manifest protects exact file versions from automatic recopy. It does not make a changed whole-file APPEND snapshot safe; only immutable/additive lab event files are suitable for this APPEND configuration.
- These CSV checks in repository CI verify file structure and fixture contracts only. They do not execute PostgreSQL, ADF, Spark, or Delta operations.

## Runtime evidence still required

On a restored disposable environment, retain:
- Source row counts before/after each PostgreSQL fixture round.
- ADF run IDs and selected watermark interval for patients.
- Patient `updated_at` values before/after the fixture updates, confirming UTC trigger behaviour.
- Manifest identity and status transitions for each CSV file version.
- Silver row counts after the 8,228-row initial lab delivery, 20-row APPEND delivery, and the 25-to-30 provider FULL snapshot rebuild.
- Gold reconciliation after both source branches complete.

A passing static check is not a substitute for this runtime evidence.
