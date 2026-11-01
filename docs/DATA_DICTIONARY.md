# HealthGrid — Data Dictionary

This dictionary describes the source entities, control metadata, medallion-layer responsibilities, and Gold analytical outputs in the HealthGrid repository.

HealthGrid was originally named **CareSync**. Some exported Azure and Databricks artifacts retain the original name in catalog and notebook paths. These are legacy environment identifiers, not separate project components.

## 1. Platform data flow

The platform integrates two source families:

- Internal hospital-system tables from PostgreSQL: hospitals, doctors, and patients.
- External partner CSV feeds in ADLS: laboratory results and insurance providers.

Azure Data Factory reads the control metadata and orchestrates ingestion. Data is landed in ADLS, loaded into Bronze Delta tables, transformed into Silver Delta tables, and published into Gold analytical tables by Databricks notebooks.

The control framework is shared across the processing stages. Active configuration rows determine which source objects and Gold outputs are processed, which load strategy applies, and which target names and execution parameters are supplied to the notebooks.

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
| updated_at | Source update timestamp and configured incremental watermark |

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

Timestamp watermark rows are seeded for PostgreSQL incremental configurations. ADLS CSV sources use the file manifest instead of `ctrl.watermark`.

### 3.3 ctrl.audit_log

| Column | Meaning |
|---|---|
| audit_id | Unique audit record identifier |
| adf_run_id | Parent ADF pipeline run identifier |
| table_id | Reference to the relevant metadata configuration |
| stage | Processing stage |
| status | IN_PROGRESS, SUCCESS, or FAILED |
| records_written | Reported output record count where available |
| start_time | Stage start time |
| end_time | Stage completion time |
| created_timestamp | Audit record creation time |

The audit table records processing status per configured object and stage, rather than relying only on a single overall pipeline status.

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
| neon_postgres | patients | patients | patients | MERGE | updated_at / patient_id |
| adls_csv | lab_results | lab_results | lab_results | APPEND | File manifest; reported_at is a business event-time field |
| adls_csv | insurance_providers | insurance_providers | insurance_providers | FULL | — |

The active metadata rows are the source of truth for the configured processing targets and strategies.

## 5. Medallion layer responsibilities

### Bronze

**Purpose:** Retain landed source batches in Delta format with ingestion context.

The Landing-to-Bronze notebook reads the configured source system and table, then adds:
- landing_timestamp: identifies the processing batch.
- insert_timestamp: records when the batch is written into Bronze.

The Bronze layer preserves source-oriented data for downstream processing and traceability.

### Silver

**Purpose:** Provide standardized, queryable Delta tables for analytical transformation.

The shared Bronze-to-Silver notebook receives the configured target table, batch timestamp, load type, and merge keys. It applies the configured FULL, APPEND, or MERGE strategy.

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

**Inputs:** Silver patients, hospitals, insurance providers, and laboratory results.

**Measures and attributes include:**
- Patient demographics and calculated age.
- Registered hospital and hospital name.
- Insurance provider identifier and name.
- Total laboratory tests.
- Abnormal and critical test counts.
- Most recent laboratory test date.

**Modeling rule:** Laboratory results are aggregated by patient before joining to the patient entity. This prevents multiple laboratory events from multiplying the patient-level output rows.

### 7.2 gold.hospital_daily_summary

**Grain:** One row per hospital and test date (hospital_id, summary_date).

**Inputs:** Silver laboratory results, hospitals, and calendar.

**Measures and attributes include:**
- Hospital name and date attributes.
- Total tests.
- Distinct patients tested.
- Distinct active doctors represented in the test activity.
- Abnormal and critical test counts.
- Abnormal and critical rates.
- Previous observed daily test volume.
- Percentage change from the previous observed daily test volume.

The previous-day comparison is based on the previous available row for that hospital in the ordered result set, not necessarily a calendar date with zero activity.

### 7.3 gold.lab_test_trends

**Grain:** One row per test name and calendar month (test_name, year, month).

**Input:** Silver laboratory results, enriched with calendar attributes.

**Measures and attributes include:**
- Test name, year, month, month name, and quarter.
- Total tests.
- Abnormal and critical test counts.
- Abnormal and critical rates.
- Previous observed month's abnormal rate.
- Change in abnormal rate versus the previous observed month.

The previous-month comparison is based on the previous available monthly row for each test name.

## 8. Key relationship and grain rules

| Relationship | Join key | Modeling consideration |
|---|---|---|
| Patients to hospitals | registered_hospital_id = hospital_id | Many patients can register at one hospital |
| Patients to insurance providers | insurance_provider_id | Logical cross-source reference |
| Patients to laboratory results | patient_id | One patient can have many test events; aggregate before patient-grain joins |
| Laboratory results to hospitals | hospital_id | Many test events can belong to one hospital |
| Laboratory results to calendar | Test date to date key | Date enrichment for reporting attributes |

## 9. Operational and interpretation notes

- PostgreSQL watermark values are stored as text in `ctrl.watermark`; source timestamp formats and comparisons must remain consistent. CSV delivery state is tracked separately in `ctrl.file_ingestion_manifest`.
- The configured patient MERGE key is patient_id; the source update timestamp is used for incremental selection.
- APPEND feeds need a clear duplicate-delivery and replay policy.
- The current source extraction pattern is watermark-based, not full change-data capture.
- Hard deletes and late-arriving changes require an explicit source contract and handling policy.
- Gold notebooks use full rebuilds, even though their selection and orchestration are metadata-driven.
- The calendar dimension has a finite configured date range.
- Source data in this educational repository is synthetic; it is not a production healthcare dataset.

## 10. Naming note

The project was initially called CareSync and was subsequently renamed HealthGrid. Some historical SQL comments, catalog names, notebook paths, and ADF references still use CareSync. When redeploying, treat these as environment-specific legacy names and align them deliberately with the target workspace. Do not infer that a legacy identifier means the corresponding pipeline was not executed successfully.
