# HealthGrid — Data Dictionary

This dictionary describes the source entities, control metadata, medallion-layer responsibilities, and Gold analytical outputs in the HealthGrid repository.

HealthGrid was originally named **CareSync**. The current repository artifacts use the HealthGrid catalog, Volume, and workspace-path conventions; the former name is retained only as project history.

## 1. Platform data flow

The platform integrates two source families:

- Internal hospital-system tables from PostgreSQL: hospitals, doctors, and patients.
- External partner CSV feeds in ADLS: laboratory results and insurance providers.

Azure Data Factory reads the control metadata and orchestrates ingestion. Data is landed in ADLS, loaded into Bronze Delta tables, transformed into Silver Delta tables, and published into Gold analytical tables by Databricks notebooks.

The control framework is shared across the processing stages. Active configuration rows determine which source objects and Gold outputs are processed, which load strategy applies, and which target names and execution parameters are supplied to the notebooks.

## 1A. Synthetic data provenance and scope

All checked-in person-level and operational records are synthetic fixtures for this portfolio implementation. The PostgreSQL source setup script generates approximately 50 hospitals, 500 doctors, and 5,000 patient records from fixed name/location lists and generated values. The laboratory CSV files are sample event feeds; insurance-provider reference files use fictional names suffixed with `Demo` and placeholder `.example` contact addresses.

The data is intended to exercise ingestion, metadata configuration, incremental processing, replay handling, data modelling, and operational analytics. It does not represent real patients, actual provider contracts, validated clinical observations, or live healthcare-system integrations. Result-status values such as `Normal`, `Abnormal`, and `Critical` are source labels used for analytical demonstration and must not be interpreted as medical findings.



## 2. Source entities

### 2.1 PostgreSQL: hospitals

| Field | Meaning |
|---|---|
| hospital_id | Primary key identifying a hospital |
| hospital_name | Facility name |
| city | Facility city |
| state | State or region |
| hospital_type | Facility classification |
| bed_count | Reported bed capacity |
| created_at | Source record creation timestamp |
| updated_at | Source record update timestamp |

**Configured load:** FULL.

**Business role:** Hospital reference data used to enrich patient and hospital-level laboratory reporting.

### 2.2 PostgreSQL: doctors

| Field | Meaning |
|---|---|
| doctor_id | Primary key identifying a doctor |
| first_name, last_name | Doctor name |
| specialty | Medical specialty |
| hospital_id | Hospital association |
| phone_number | Contact number in the synthetic source |
| created_at | Source record creation timestamp |
| updated_at | Source record update timestamp |

**Configured load:** FULL.

**Business role:** Doctor roster and hospital association used in hospital-level reporting.

### 2.3 PostgreSQL: patients

| Field | Meaning |
|---|---|
| patient_id | Primary key identifying a patient |
| first_name, last_name | Patient name |
| date_of_birth | Date of birth |
| gender | Source gender value |
| city, state | Patient location |
| registered_hospital_id | Hospital at which the patient is registered |
| insurance_provider_id | Logical reference to the partner insurance-provider feed |
| created_at | Source record creation timestamp |
| updated_at | UTC source update timestamp and configured incremental watermark |

**Configured load:** MERGE.

**Merge key:** patient_id.

**Watermark:** updated_at.

**Business role:** Patient-level demographic and registration information used by the Patient 360 dataset.

The insurance-provider relationship is logical: the provider data is sourced from a separate ADLS CSV feed, so the PostgreSQL source does not declare a database-enforced foreign key to that file.

### 2.4 ADLS CSV: lab_results

The partner laboratory feed contains test-result events. The supplied sample files are stored under the source and incremental-load folders.

**Configured load:** APPEND.

**Watermark field:** reported_at in the source metadata configuration.

**Business role:** Primary event fact used to calculate patient laboratory activity, hospital daily metrics, and monthly test trends.

The analytical notebooks use fields including patient_id, hospital_id, doctor_id, test_date, test_name, and result_status. The reporting logic classifies results using the Abnormal and Critical status values.

### 2.5 ADLS CSV: insurance_providers

The partner insurance feed supplies insurance-provider reference data.

**Configured load:** FULL.

**Business role:** Enriches patient-level reporting with the provider name associated with each patient's insurance_provider_id.

The Gold patient-level model uses insurance_provider_id to join the patient record to the provider reference data.

## 3. Control and metadata schema

The control database uses the ctrl schema.

### 3.1 ctrl.table_config

One configuration row represents a source object/file or a Gold output. This is the central metadata registry used by the ADF orchestration framework.

| Column | Meaning |
|---|---|
| table_id | Unique metadata row identifier |
| source_system | Source family identifier, such as neon_postgres, adls_csv, or silver |
| source_schema_name | Source database schema where applicable |
| source_table_name | Source table or logical file name |
| source_file_format | File format, such as CSV |
| source_path | Source folder/path for file-based inputs |
| bronze_table_name | Bronze target name |
| silver_table_name | Silver target name |
| gold_table_name | Gold output name |
| load_type | Configured strategy: FULL, APPEND, or MERGE |
| watermark_column | Source field used for incremental selection |
| watermark_lookback_minutes | Number of minutes re-read before the persisted checkpoint; non-negative and configured per source object |
| merge_keys | Comma-separated business key fields for MERGE |
| stage | SOURCE_TO_SILVER or SILVER_TO_GOLD |
| is_active | Controls whether the configuration is selected for execution |
| created_timestamp | Metadata row creation time |
| updated_timestamp | Metadata row update time |

**How it drives processing**

- The source orchestration pipeline selects active rows for the requested source_system.
- The inner ingestion pipeline reads the selected row and passes its configuration to the source-copy and Databricks notebook activities.
- Load type controls whether a watermark lookup is required and which Silver write strategy is used.
- Gold orchestration selects active SILVER_TO_GOLD rows and dynamically resolves the corresponding notebook using gold_table_name.
- The metadata table therefore drives source selection, processing configuration, target selection, and orchestration across the layers.

### 3.2 ctrl.watermark

| Column | Meaning |
|---|---|
| table_id | Primary key and reference to ctrl.table_config |
| watermark_value | Persisted timestamp checkpoint for timestamp-watermarked sources (PostgreSQL in this project) |
| last_updated_timestamp | Time the checkpoint record was updated |

Timestamp watermark rows are seeded for PostgreSQL incremental configurations. ADLS CSV sources use the file manifest instead of `ctrl.watermark`. The patients source is seeded with a five-minute lookback; other source metadata defaults to zero. ADF captures a UTC run-start upper bound and extracts `[previous_watermark - lookback, run_start_upper_bound)`. After Silver succeeds, the checkpoint is advanced to that captured upper bound using a monotonic update. The PostgreSQL source DDL maintains `patients.updated_at` with a UTC `BEFORE UPDATE` trigger.

### 3.3 ctrl.audit_log

| Column | Meaning |
|---|---|
| audit_id | Unique audit record identifier |
| adf_run_id | Parent ADF pipeline run identifier |
| table_id | Reference to the relevant metadata configuration |
| stage | Processing stage |
| status | IN_PROGRESS, SUCCESS, or FAILED |
| records_written | Logical output rows written by the stage. For SOURCE_TO_SILVER, FULL and APPEND report successfully written input rows; an initial MERGE load reports its initial target rows; an existing Delta MERGE reports inserted plus updated target rows, excluding stale and equal-version no-op records. NO_DATA reports zero. |
| start_time | Stage start time |
| end_time | Stage completion time |
| created_timestamp | Audit record creation time |

The audit table records processing status per configured object and stage, rather than relying only on a single overall pipeline status. For SOURCE_TO_SILVER, `records_written` is not the Bronze source-row count for an existing MERGE: it is derived from the identified Delta commit's `numTargetRowsInserted` plus `numTargetRowsUpdated` operation metrics. A per-commit metadata marker combines the ADF run ID, table, and landing batch so another table write cannot be mistaken for this run's result. Stale rows and equal-version identical payloads contribute zero written rows. If the exact commit or required metrics cannot be identified, the notebook fails instead of publishing a misleading count. A unique constraint on `(adf_run_id, table_id, stage)` enforces one summary row per parent run, object, and stage. Start activities use an idempotent upsert; a retry resets the same row to IN_PROGRESS rather than adding another row. This is a latest-attempt summary, while detailed retry history remains in ADF run/activity history. For `SILVER_TO_GOLD`, `records_written` is the validated row count of the fully rebuilt Gold output table (`CREATE OR REPLACE TABLE`), not a net changed-row count. Each Gold notebook returns the final materialized table count only after its schema, grain, and metric assertions pass.

### 3.4 ctrl.file_ingestion_manifest

| Column | Meaning |
|---|---|
| file_manifest_id | Unique file-version manifest record |
| table_id | Reference to the source metadata configuration |
| source_path | Configured source folder |
| source_file_name | Name of the individual CSV file |
| source_last_modified | Last-modified timestamp observed by ADF |
| source_file_size | File size in bytes |
| source_content_md5 | ADLS content MD5 when available; empty when unavailable |
| status | IN_PROGRESS, COPIED, PROCESSED, or FAILED |
| adf_run_id | Parent ADF run that currently owns the file version |
| landing_path | Timestamped landing folder for the copied file |
| last_error | Copy error detail where available |
| discovered_timestamp | First manifest record creation time |
| updated_timestamp | Most recent state update time |
| processed_timestamp | Time the file version reached PROCESSED |

The unique file-version identity combines table_id, source_path, source_file_name, source_last_modified, source_file_size, and source_content_md5. PROCESSED means the file has completed the Bronze-to-Silver path. Previous-run IN_PROGRESS/COPIED entries are blocked for manual reconciliation rather than automatically recopied.

## 4. Configured source-to-Silver objects

| Source system | Source object | Bronze target | Silver target | Strategy | Watermark / key |
|---|---|---|---|---|---|
| neon_postgres | hospitals | hospitals | hospitals | FULL | — |
| neon_postgres | doctors | doctors | doctors | FULL | — |
| neon_postgres | patients | patients | patients | MERGE | updated_at / patient_id; 5-minute lookback |
| adls_csv | lab_results | lab_results | lab_results | APPEND | File manifest; reported_at is a business event-time field |
| adls_csv | insurance_providers | insurance_providers | insurance_providers | FULL | — |

The active metadata rows are the source of truth for the configured processing targets and strategies.

## 5. Medallion layer responsibilities

### Bronze

**Purpose:** Retain landed source batches in Delta format with ingestion context.

The Landing-to-Bronze notebook validates the source system, Bronze table, landing timestamp, load strategy, and source format before reading the batch. It adds:
- `landing_timestamp`: the ADF-generated batch identifier shared by the Landing-to-Bronze and Bronze-to-Silver stages.
- `insert_timestamp`: the timestamp at which the DataFrame is written into Bronze.

The notebook appends each non-empty batch to its Bronze Delta table. It rejects source fields that collide with these reserved metadata names, case-insensitive duplicate column names, and field additions/removals/data-type changes against an existing Bronze schema. The current policy is fail-closed: schema evolution requires a reviewed migration rather than automatic schema merging. The same landing timestamp cannot be appended twice to an existing Bronze target.

The batch guard is not a business-key deduplication mechanism. Identical business events delivered under a different ADF landing timestamp can still be appended again. The Bronze layer preserves source-oriented data for downstream processing and traceability.

### Silver

**Purpose:** Provide standardized, queryable Delta tables for analytical transformation.

The shared Bronze-to-Silver notebook receives the target table, landing timestamp, load type, merge keys, and metadata `watermark_column` as the MERGE source-version field. It reads only the Bronze batch identified by that landing timestamp.

**Write strategies**
- **FULL:** overwrite the Silver target with the current complete batch. Missing or invalid load metadata fails closed; the notebook does not silently assume FULL. The Landing-to-Bronze step rejects empty FULL extracts before the Silver overwrite.
- **APPEND:** append the current batch. This strategy does not deduplicate business records across different landing timestamps. The CSV manifest protects an exact processed file version from automatic recopy, but changed whole-file snapshots or new batches containing previously ingested events can still duplicate rows.
- **MERGE:** insert unseen business keys and update a matched row only when the incoming source version is strictly newer than the target version.

**MERGE validation and ordering contract**
- Metadata must supply one or more merge keys and a source-version column. The version column must resolve to exactly one source column and have DATE or TIMESTAMP type.
- Source keys must be non-null and unique within the batch; source versions must be non-null. The notebook rejects duplicate keys rather than selecting an arbitrary winner.
- When the target exists, column names and data types must match the incoming source schema. Case-insensitive column-name collisions are rejected. Target keys must be non-null and unique, and target source-version values must be non-null.
- A strictly newer source version updates the matched row; an older source version is skipped. An equal-version row with identical business payload is a no-op, while an equal-version row with changed business payload is rejected. Landing/insert/update timestamps are treated as technical metadata, not business payload, for this equality check.
- A missing target is initialized from the validated source batch.

The notebook accepts explicit DATA/NO_DATA landing status. NO_DATA exits without a Silver write; a DATA hand-off with no matching Bronze rows fails rather than reporting a successful empty load. Table names and landing-batch identifiers are validated before they are interpolated into Spark identifiers or batch filters.

The final notebook count is the number of source Bronze rows processed for the batch; for MERGE, it is not a count of inserted or updated target rows. All Databricks behavior still requires runtime validation; passing repository CI verifies static code and contract checks, not Delta execution.

The Silver layer includes the source entities and the reusable calendar dimension.

### Gold

**Purpose:** Publish business-oriented datasets selected through Gold-stage metadata.

The Gold ADF pipeline reads active Gold metadata rows and dynamically selects the corresponding notebook. Each notebook contains the SQL transformation logic for its analytical output.

The Gold execution pattern is metadata-driven, while individual dataset transformation logic is maintained in the relevant Databricks notebook. The current Gold notebooks use full table replacement when rebuilding their targets.

## 6. Silver calendar dimension

The calendar notebook creates a reusable date dimension covering 1940-01-01 through 2030-12-31.

It includes date keys and common reporting attributes such as day, week, month, quarter, year, month name, weekend indicator, period boundaries, and leap-year information.

Gold reporting uses the calendar to enrich date-based metrics and provide consistent reporting labels.

## 7. Gold analytical datasets

### 7.1 gold.patient_360

**Grain:** One intended row per patient (patient_id).

**Inputs:** Silver patients, hospitals, insurance_providers, and lab_results.

**Attributes and measures:**
- Patient identifiers, demographic fields, and registered location.
- Registered hospital ID/name and insurance-provider ID/name.
- total_tests: count of Silver laboratory events for the patient.
- abnormal_test_count and critical_test_count: counts of events carrying those source status labels.
- last_test_date: maximum laboratory test_date for the patient.
- age: FLOOR(datediff(current_date(), date_of_birth) / 365.25), calculated when the Gold notebook rebuilds the table.

**Modeling rules and considerations:**
- Laboratory results are aggregated by patient before joining to the patient entity. This prevents multiple laboratory events from multiplying patient rows.
- Hospital, provider, and laboratory activity are left-joined so a patient remains in the output when a lookup or laboratory record is absent. Missing enrichment remains NULL; missing lab counts are set to zero and the last test date remains NULL.
- The intended grain assumes hospital and insurance-provider identifiers are unique in their Silver reference tables. The notebook now checks the resulting patient key is non-null and unique, so duplicate lookup keys that multiply a patient row fail the notebook contract.
- Age is an approximate whole-year calculation and represents age at the time of the rebuild, not a continuously refreshed value. The table must be rebuilt to recalculate age.

### 7.2 gold.hospital_daily_summary

**Grain:** One row per hospital and test date (hospital_id, summary_date).

**Inputs:** Silver lab_results, hospitals, and calendar.

**Attributes and measures:**
- Hospital name and calendar date attributes (day_name, is_weekend).
- total_tests: count of lab-result events for the hospital/date.
- unique_patients_tested: distinct patient IDs represented in those events.
- active_doctor_count: distinct doctor IDs represented in those events; this is not a count of the hospital's full doctor roster.
- Abnormal and critical event counts, using the source result_status labels.
- abnormal_rate_pct and critical_rate_pct: corresponding status count divided by total tests, multiplied by 100 and rounded to two decimal places.
- prev_day_total_tests: previous available summary row's test count for that hospital.
- test_volume_change_pct: relative change, (current total - previous total) / previous total * 100, rounded to two decimals.

**Time-series interpretation:** The SQL uses LAG over the dates present for each hospital. It does not create rows for dates with no laboratory events. Therefore, the previous-row values compare against the previous available observation, which may not be the immediately preceding calendar day. The legacy output column name prev_day_total_tests is retained for compatibility; interpret it as the previous observed date. The first observed row, or a row whose previous total is zero, has a NULL percentage change.

### 7.3 gold.lab_test_trends

**Grain:** One row per test name and calendar month (test_name, year, month).

**Inputs:** Silver lab_results, enriched with calendar month attributes.

**Attributes and measures:**
- Test name, year, month number, month name, and quarter.
- Total tests, abnormal test count, and critical test count for each test/month.
- abnormal_rate_pct and critical_rate_pct: corresponding status count divided by monthly total tests, multiplied by 100 and rounded to two decimal places.
- prev_month_abnormal_rate_pct: abnormal rate from the previous available monthly row for the same test.
- abnormal_rate_change_pct: current abnormal rate minus the previous available abnormal rate, rounded to two decimal places.

**Time-series interpretation:** The SQL uses LAG over months present for each test. It does not create zero-activity month rows, so the previous observation may be earlier than the immediately preceding calendar month. Despite the output suffix _pct, abnormal_rate_change_pct is a percentage-point difference (for example, 12.00% to 15.00% produces +3.00 percentage points), not a relative percent change. The first observed month has NULL prior-rate/change values.

### 7.4 Gold notebook output contracts

Before each notebook returns its row count, it now checks:
- Required output columns are present.
- Grain keys are non-null and unique (patient_id; hospital_id, summary_date; or test_name, year, month).
- Counts are non-negative and do not exceed the corresponding total-test denominator.
- Rate percentages are between 0 and 100; the abnormal-rate percentage-point change is between -100 and +100.

These checks execute inside Databricks after the table rebuild. They are present in the repository, but require a restored Databricks environment and representative data to obtain runtime pass evidence. Static CI does not execute Spark SQL or these DataFrame assertions.

## 8. Key relationship and grain rules

| Relationship | Join key | Modeling consideration |
|---|---|---|
| Patients to hospitals | registered_hospital_id = hospital_id | Many patients can register at one hospital |
| Patients to insurance providers | insurance_provider_id | Logical cross-source reference |
| Patients to laboratory results | patient_id | One patient can have many test events; aggregate before patient-grain joins |
| Laboratory results to hospitals | hospital_id | Many test events can belong to one hospital |
| Laboratory results to calendar | Test date to date key | Date enrichment for reporting attributes |

## 9. Operational and interpretation notes

- PostgreSQL watermark values are stored as text in `ctrl.watermark`; source timestamp formats and comparisons must remain consistent. CSV delivery state is tracked separately in `ctrl.file_ingestion_manifest`. Patient source `updated_at` values are stored as timestamp-without-time-zone values normalized to UTC by the supplied source SQL.
- The configured patient MERGE key is patient_id; the source update timestamp is used for incremental selection.
- APPEND feeds need a clear duplicate-delivery and replay policy.
- The current source extraction pattern is watermark-based, not full change-data capture.
- The five-minute overlap mitigates short transaction delays and replay gaps, but changes arriving later than the configured window can still be missed.
- Hard deletes are not captured; a source delete contract, soft-delete field, or CDC mechanism is required if deletes must propagate.
- The source must update `updated_at` on every relevant mutation and keep it in UTC. Runtime proof of boundary, concurrency, and late-arrival scenarios still requires a restored Azure environment.
- Gold notebooks use full rebuilds, even though their selection and orchestration are metadata-driven.
- The calendar dimension has a finite configured date range.
- Source data in this educational repository is synthetic; it is not a production healthcare dataset.

## 10. Naming note

The project was initially called CareSync and was subsequently renamed HealthGrid. The repository's technical artifacts now use HealthGrid naming conventions. During redeployment, replace only the explicit linked-service placeholders and verify that the target workspace contains the documented `/Shared/HealthGrid/` notebooks and `healthgrid` Unity Catalog objects.
