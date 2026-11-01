# HealthGrid — Validation and Testing Plan

This plan defines how to validate the HealthGrid metadata-driven platform from source ingestion through Gold analytics.

The project was historically executed end-to-end successfully. The cases below are a repeatable validation specification for future deployments and changes; listing a test does not mean it has been rerun against a currently available Azure environment.

## 1. Validation objectives

Validation must establish that:
1. Active metadata selects the intended source objects and Gold outputs.
2. ADF passes the correct configuration and batch context to Databricks.
3. Landing and Bronze preserve the expected source batch and ingestion metadata.
4. Silver applies the configured FULL, APPEND, or MERGE strategy correctly.
5. Watermarks and audit records reflect verified processing outcomes.
6. Gold datasets meet their declared grain, relationship, and business-metric definitions.
7. Failures can be detected and recovered without silent data loss or uncontrolled duplication.

## 2. Test evidence

Use a disposable environment with synthetic data. Do not run destructive setup scripts against production data.

For each test, retain the test ID, objective, environment/version, ADF parent and child run IDs, metadata table_id and parameters, source fixture, expected result, ADF and Databricks outputs, before/after watermark and audit records, row counts, SQL assertions, and pass/fail result.

These tests require execution in a configured Azure environment. Static inspection or a successful packaging workflow is not a substitute for runtime validation.

## 3. Metadata framework tests

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| META-01 | Active source selection | Configure active and inactive source rows; run source selection | Only active rows for the requested source system are selected |
| META-02 | Active Gold selection | Configure active and inactive Gold rows | Only active SILVER_TO_GOLD rows are selected |
| META-03 | Dynamic Gold notebook selection | Execute configured Gold outputs | Notebook path resolves from gold_table_name; each output is processed once |
| META-04 | Load strategy routing | Exercise FULL, APPEND, and MERGE | Configured strategy reaches the shared Silver notebook unchanged |
| META-05 | Missing watermark | Remove a required APPEND/MERGE watermark in a test environment | Run fails clearly before unsafe extraction |
| META-06 | Invalid merge configuration | Supply empty or invalid merge keys | Validation fails before target mutation |
| META-07 | Inactive configuration | Set is_active to false | Object is excluded from processing |
| META-08 | Audit lifecycle | Execute successful and failed table-stage runs | Audit state/timestamps reflect actual outcomes; no false SUCCESS |

## 4. Source extraction and ADF orchestration

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| ADF-01 | PostgreSQL FULL | Run hospitals and doctors as FULL | Extracted rows reconcile to source snapshot |
| ADF-02 | PostgreSQL MERGE extraction | Insert and update patient records with valid updated_at values | Expected new/changed records reach landing |
| ADF-03 | CSV initial ingestion | Run initial lab-results and insurance-provider feeds | Expected files reach the correct timestamped landing paths |
| ADF-04 | CSV incremental selection | Add a new file version and run again | Only file versions not already marked PROCESSED in the manifest are copied |
| ADF-05 | Landing path construction | Inspect ADF sink path and notebook parameters | Source system, metadata object, 24-hour millisecond timestamp, and ADF run ID identify the same batch |
| ADF-09 | PostgreSQL schema metadata | Set source_schema_name to a non-default schema in a disposable source | Copy query reads the configured schema rather than a hardcoded schema |
| ADF-10 | Copy returns no rows/files | Test a PostgreSQL query returning zero rows and an ADLS source with no eligible files | A successful empty Copy reaches explicit no-data handling; a Copy-level no-file failure is surfaced distinctly and does not become a false SUCCESS |
| ADF-06 | Source connection failure | Use unavailable endpoint or invalid test credential | Failure is visible; downstream does not treat missing data as a successful empty batch |
| ADF-07 | Source branch failure | Force one source branch to fail | Failure is identifiable; Gold is not accepted solely because master continued |
| ADF-08 | Concurrent execution | Trigger overlapping runs for the same source | No landing collision, checkpoint race, or unintended overwrite |

**Orchestration gate:** the master pipeline now requires both source branches to be Succeeded before starting Gold. Test each source branch failing independently and verify Gold is skipped. The notification branch intentionally runs after Gold is Completed so it can report success or failure.

## 5A. CSV file manifest tests

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| FILE-01 | Folder enumeration | Run Get Metadata against a populated source folder | Direct child items are returned; only file items with a .csv extension enter the ForEach |
| FILE-02 | File identity | Inspect manifest values for a source file | Identity contains table_id, source path/name, lastModified, size, and content MD5 where available |
| FILE-03 | Processed file skip | Run the same source inventory after a version reaches PROCESSED | Exact file version is not copied again |
| FILE-04 | Changed file version | Replace a file with changed lastModified, size, or content MD5 | New version is treated as a new delivery and is copied once |
| FILE-05 | Copy state transition | Allow file Copy to succeed | Manifest moves IN_PROGRESS to COPIED; it is not yet PROCESSED |
| FILE-06 | End-to-end state transition | Complete Landing-to-Bronze and Bronze-to-Silver | All COPIED files for the table/run become PROCESSED |
| FILE-07 | Copy failure | Force a per-file Copy failure | Manifest records FAILED and failure remains visible in ADF |
| FILE-08 | Downstream failure after Copy | Copy succeeds, then fail Landing-to-Bronze or Silver | Manifest remains COPIED; next run blocks automatic recopy until original landing batch is reconciled |
| FILE-09 | Empty source folder | Use an existing folder with no CSV files | Zero file iterations; incremental load records NO_DATA/zero rows; FULL fails closed |
| FILE-10 | Missing or inaccessible folder | Remove folder or revoke list permission | Get Metadata fails visibly; it is not misclassified as an empty feed |
| FILE-11 | Concurrent same-file runs | Start two runs for the same file version | Unique manifest identity and state checks prevent silent duplicate copy; conflicting run fails closed |
| FILE-12 | Missing content MD5 | Use a file for which Get Metadata returns no contentMD5 | Manifest falls back to path/name/lastModified/size; limitation is recorded |
| FILE-13 | Mutable full-file delivery | Replace an already processed CSV with a revised whole-file snapshot | APPEND duplication risk is demonstrated and a source immutability or row-level deduplication policy is required |

The manifest state machine is a conservative file-level replay guard. It does not make ADLS Copy, Delta writes, and Azure SQL manifest updates one atomic transaction. A COPIED state after downstream failure must be reconciled rather than automatically retried.
## 5. Landing and Bronze tests

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| BRZ-01 | Parquet landing read | Land PostgreSQL fixture and execute Landing-to-Bronze | Bronze rows and values reconcile to landing files |
| BRZ-02 | CSV landing read | Land CSV fixture and execute Landing-to-Bronze | Header handling and types are correct; rows reconcile |
| BRZ-03 | Ingestion metadata | Inspect Bronze rows | Every row has expected landing_timestamp and populated insert_timestamp |
| BRZ-04 | Multiple batches | Land two batches for one object | Each batch remains identifiable by landing timestamp |
| BRZ-05 | Missing landing directory | Invoke notebook with non-existent batch path and accessible source/table parents | Incremental load returns `NO_DATA`; FULL load fails; no Bronze rows are written |
| BRZ-06 | Empty landing directory | Invoke notebook with existing empty path for FULL and incremental configurations | FULL fails safely; incremental returns `NO_DATA`; no empty batch is appended to Bronze |
| BRZ-07 | Replay same batch | Process the same landing timestamp twice | Second Bronze append is rejected before mutation when that batch already exists |
| BRZ-10 | Schema drift | Add/remove a field or change a field type after the Bronze schema is established | Bronze append fails with a clear drift report before target mutation; reviewed migration is required |
| BRZ-11 | New-run replay | Re-run source extraction so the same source records land under a new ADF run ID | Test demonstrates that batch-ID protection alone does not deduplicate the same business records across newly identified batches; apply the intended APPEND deduplication/manifest policy |
| BRZ-08 | Schema drift | Add, remove, or change a source field | Drift is detected or handled by explicit policy; no silent incorrect coercion |
| BRZ-09 | ADF no-data status propagation | Run an incremental source that produces no landing records | Landing-to-Bronze returns `NO_DATA`; ADF passes that status to Silver; Silver exits with zero rows; checkpoint remains unchanged; audit records SUCCESS with zero rows |

The current Landing-to-Bronze notebook appends rows and adds batch/insert timestamps. It rejects exact same-timestamp batch replay and fails closed on Bronze schema drift. It does not deduplicate identical source records re-extracted into a new batch ID; BRZ-11 remains a key reliability test. Schema validation is static code evidence until run in Databricks.

## 6. Silver transformation tests

### FULL strategy

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| SLV-01 | Initial FULL load | Load known source snapshot | Silver contains the expected complete snapshot |
| SLV-02 | FULL overwrite | Change fixture and run FULL again | Silver reflects new snapshot and does not retain obsolete rows |
| SLV-03 | Empty FULL batch | Supply an empty or missing FULL landing batch | Landing-to-Bronze fails before Bronze-to-Silver; existing Silver target is not overwritten |

### APPEND strategy

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| SLV-04 | Initial APPEND | Load known lab-results batch | Silver increases by expected row count |
| SLV-05 | Second APPEND | Load disjoint second batch | Existing rows remain and new rows are added |
| SLV-06 | Duplicate replay | Reprocess same batch | Duplicates are detected; replay policy prevents or explicitly tolerates them |
| SLV-07 | Empty APPEND | Process valid empty batch | Silver write is skipped; existing Silver rows and watermark remain unchanged |

### MERGE strategy

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| SLV-08 | Initial MERGE | Run patient MERGE when target does not exist | Target is created with expected rows |
| SLV-09 | New key | Add patient with new patient_id | Exactly one new target row is inserted |
| SLV-10 | Existing key update | Change patient field and advance updated_at | Existing row is updated, not duplicated |
| SLV-11 | Repeated unchanged record | Reprocess same patient values | One row remains per patient_id |
| SLV-12 | Duplicate source keys | Supply two source rows with same merge key | Batch is rejected or deterministically reduced before MERGE |
| SLV-13 | Null merge key | Supply null patient_id | Invalid row is rejected/quarantined |
| SLV-14 | Late/out-of-order update | Process older source version after newer target version | Older data cannot overwrite newer data, or limitation is explicitly accepted |
| SLV-15 | Missing merge-key column | Remove patient_id from fixture | Notebook fails before target mutation |
| SLV-16 | Empty MERGE batch | Process an incremental batch with no records | Silver write is skipped; existing target remains unchanged; checkpoint is not advanced |

The current MERGE notebook checks that configured key columns exist, but does not itself prove source-key uniqueness or compare source versions against target versions. SLV-12 and SLV-14 are explicit hardening gates.

## 7. Watermark and checkpoint tests

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| WMR-01 | Initial checkpoint | Run incremental object with seeded historical watermark | Expected initial history is selected |
| WMR-02 | Successful checkpoint | Complete extraction and Silver processing | Checkpoint update occurs only after required processing succeeds; success audit waits for checkpoint activity success |
| WMR-03 | Failed Silver write | Force Silver notebook failure | Watermark does not advance |
| WMR-04 | Failed checkpoint update | Allow Silver write, then fail checkpoint activity | Target/checkpoint discrepancy is observable and recoverable; success audit is not written and parent failure handling records FAILED |
| WMR-05 | Equal timestamp boundary | Create source change at exact stored checkpoint | No eligible change is silently skipped |
| WMR-06 | Late-arriving update | Add update with older source timestamp after later checkpoint | Defined lookback/CDC policy captures it, or limitation is accepted |
| WMR-07 | Clock/time-zone difference | Use source and orchestration timestamps with known offsets | Comparisons use consistent documented time basis |
| WMR-08 | Null/malformed watermark | Supply invalid checkpoint | Pipeline fails clearly before unsafe query |
| WMR-09 | Per-object isolation | Process two incremental objects | One object's checkpoint does not alter the other's |
| WMR-10 | Checkpoint recovery | Restore verified prior checkpoint in disposable environment | Backfill reconciles without silent loss or uncontrolled duplication |

**Critical implementation-specific test:** the current ADF pipeline advances the PostgreSQL timestamp watermark to SYSUTCDATETIME(), rather than the maximum source timestamp actually observed. Test the extraction/checkpoint interval, late arrivals, and source clock behavior before relying on this design for production completeness. ADLS CSV selection is manifest-based and does not use `ctrl.watermark`.

## 8. Audit and failure-path tests

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| AUD-01 | Start audit | Start table-stage execution | IN_PROGRESS record is associated with expected ADF run and table |
| AUD-02 | Success audit | Complete notebook, checkpoint control (or valid FULL/no-data skip), and success activity | SUCCESS, end time, and records_written reflect execution; incremental no-data is SUCCESS with zero rows |
| AUD-03 | Failure audit | Force upstream notebook/activity failure | FAILED status identifies table and stage |
| AUD-04 | Audit update failure | Fail audit update after data write and checkpoint success | Data/checkpoint success and audit failure are distinguishable |
| AUD-05 | Stale IN_PROGRESS | Simulate interrupted run | Stale execution is discoverable and reconcilable to ADF history |
| AUD-06 | Multiple runs | Execute same table in separate ADF runs | Audit records associate with correct run |

Check whether the current audit update predicate, using adf_run_id and table_id, can match multiple rows if a table is retried within one parent run. If so, introduce a unique execution identifier or target the specific audit row.

## 9. Gold analytical validation

### Patient 360

**Expected grain:** one row per patient_id.

| ID | Test | Acceptance criteria |
|---|---|---|
| GLD-01 | Patient uniqueness | No patient_id appears more than once |
| GLD-02 | Patient coverage | Gold population reconciles to intended Silver patient population |
| GLD-03 | Lab aggregation | Test, abnormal, and critical counts match independent Silver aggregation per patient |
| GLD-04 | Join cardinality | Hospital and insurance enrichment does not multiply patient rows |
| GLD-05 | Missing dimension match | Unmatched hospital/provider behavior follows documented null/default policy |
| GLD-06 | Age derivation | Age is correct for documented as-of date and DOB policy |

### Hospital daily summary

**Expected grain:** one row per hospital_id and summary_date.

| ID | Test | Acceptance criteria |
|---|---|---|
| GLD-07 | Composite grain uniqueness | No duplicate hospital/date combination |
| GLD-08 | Test volume | Totals reconcile to Silver lab events by hospital/date |
| GLD-09 | Distinct counts | Patient and doctor counts match independent distinct-count queries |
| GLD-10 | Abnormal/critical metrics | Counts match source classifications and do not exceed total tests |
| GLD-11 | Rates | Rates match documented numerator/denominator and zero-denominator policy |
| GLD-12 | Previous-day comparison | LAG and percentage change match previous available row per hospital |

### Lab test trends

**Expected grain:** one row per test_name, year, and month.

| ID | Test | Acceptance criteria |
|---|---|---|
| GLD-13 | Composite grain uniqueness | No duplicate test/month combination |
| GLD-14 | Monthly volume | Totals reconcile to Silver lab results by test/month |
| GLD-15 | Abnormal/critical counts | Counts reconcile to independently grouped Silver results |
| GLD-16 | Rates | Rates match documented denominator and zero-denominator policy |
| GLD-17 | Previous-month comparison | LAG value/change matches previous available month per test |

### Gold rebuild behavior

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| GLD-18 | Repeated Gold run | Execute same notebook twice against unchanged Silver | Results are equivalent; duplicates do not accumulate |
| GLD-19 | Silver input change | Change Silver fixture and rebuild Gold | Gold reflects changed input |
| GLD-20 | Gold notebook failure | Force failure during rebuild | Target is inspected and recoverable; partial publication is not accepted |
| GLD-21 | Parallel Gold execution | Run configured notebooks concurrently | Each target is written once; no resource or metadata collision |

## 10. Cross-layer reconciliation

For each source object, compare the expected source interval to the landing batch, Bronze batch, and Silver result. Raw row counts need not match across layers when transformations, filtering, deduplication, or aggregation intentionally change grain.

Reconcile Gold at business grain:
- Patient 360 against patient entities and independently grouped lab activity.
- Hospital daily summary against hospital/date laboratory aggregates.
- Lab test trends against test/month laboratory aggregates.

Document excluded, rejected, duplicated, or late-arriving records. Every difference must have an explainable rule and evidence trail.

## 11. Release acceptance gates

| Gate | Required evidence | Exit criterion |
|---|---|---|
| G1 — Configuration | Active metadata, required watermarks, valid targets | Intended objects resolve correctly |
| G2 — Source/landing | ADF outputs and landing inventory | Expected source records/files are present |
| G3 — Bronze | Batch timestamps, counts, schema checks | Batch is traceable and reconciled |
| G4 — Silver | Strategy tests, keys, counts, watermark | Correct write semantics and checkpoint state |
| G5 — Gold | Grain and business-metric assertions | All three Gold outputs reconcile |
| G6 — Recovery | Failure injection and rerun evidence | Recovery does not silently lose or duplicate data |
| G7 — Orchestration | Parent/child outcomes and audit trail | Failed upstream work cannot be accepted as successful end-to-end run |
| G8 — Sign-off | Test report, exceptions, owner, run IDs | Critical tests pass or have explicit accepted exception |

## 12. Sign-off record

Record release/deployment identifier, workspace/environment, test date, ADF run IDs, test IDs passed/failed/blocked, known exceptions, reconciliation evidence, checkpoint values, reviewer, and approval decision.

A test is PASS only when its acceptance criteria are supported by captured evidence. A test case, static code review, or historical successful execution does not prove that a new deployment or code change has passed that test.
