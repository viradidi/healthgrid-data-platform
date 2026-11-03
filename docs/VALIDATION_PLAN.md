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

## 2A. Automated validation layers

HealthGrid separates repository checks from cloud integration execution so normal code review does not unexpectedly provision or consume Azure compute.

### Repository validation — automatic

The [repository validation workflow](../.github/workflows/healthgrid-validation.yml) runs on relevant pushes and pull requests. It performs static checks on JSON exports, notebook structure and Python code-cell syntax, Python files, ADF/Databricks configuration contracts, required documentation, the protected architecture embed, and selected credential patterns. Its path filters include `.sql`, `.csv`, `.xlsx`, and `assets/**` so changes to source/control SQL and data/mapping assets are not silently excluded.

A passing result establishes repository consistency and selected code/configuration contracts. It does **not** prove that Azure connections, ADF expressions, Databricks runtime behavior, Unity Catalog permissions, Delta operations, or business results work in a deployed environment.

### Azure integration validation — manual and environment-gated

The [Azure integration workflow](../.github/workflows/healthgrid-azure-integration.yml) can be started manually after a disposable DEV environment has been restored. It requires an explicit confirmation input and uses the GitHub Environment named `healthgrid-integration`. It starts the ADF `PL_MASTER` pipeline and polls the ADF run status. The master pipeline is expected to invoke the source-to-Silver branches, the Silver-to-Gold pipeline, and the Databricks notebook activities configured in ADF.

The workflow requires GitHub Environment secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`, plus Environment variables `HEALTHGRID_AZURE_RESOURCE_GROUP` and `HEALTHGRID_AZURE_DATA_FACTORY_NAME`. Configure Microsoft Entra workload identity federation for the subject `repo:viradidi/healthgrid-data-platform:environment:healthgrid-integration` and audience `api://AzureADTokenExchange`. Scope a least-privilege custom role to the target Data Factory with permissions to read the factory/pipeline/run, create a pipeline run, and cancel a run created by this workflow. Do not grant subscription-wide Contributor solely for this check.

Before triggering it:
- Restore and publish the ADF factory and confirm all linked services, Key Vault references, Databricks workspace/compute, notebook paths, source systems, and metadata are valid.
- Ensure the target is a disposable DEV environment containing only synthetic data. `PL_MASTER` runs the configured sources and Gold rebuild; it can overwrite targets and invoke the notification path.
- Configure the `healthgrid-integration` GitHub Environment with an approval requirement where available. Do not configure this workflow to run automatically on pull requests or pushes.

On completion, retain the ADF run ID and inspect individual activity runs, Databricks notebook outputs, audit rows, watermarks, row counts, and Gold-grain reconciliations. A workflow result of `Succeeded` confirms the master pipeline reached a successful terminal state; it does not independently prove every test case in this plan has passed.

The original Azure resources were decommissioned after the project was completed to control cost. Therefore, this live workflow has been added as a gated capability but has **not** been executed against a currently restored environment.

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
| ADF-10 | Empty incremental PostgreSQL extraction | Use a watermark beyond all available source rows | Confirm ADF Copy behavior; Landing returns NO_DATA where no file is produced, Silver and watermark stay unchanged, and the run records a successful zero-row outcome |
| ADF-10 | Copy returns no rows/files | Test a PostgreSQL query returning zero rows and an ADLS source with no eligible files | A successful empty Copy reaches explicit no-data handling; a Copy-level no-file failure is surfaced distinctly and does not become a false SUCCESS |
| ADF-06 | Source connection failure | Use unavailable endpoint or invalid test credential | Failure is visible; downstream does not treat missing data as a successful empty batch |
| ADF-07 | Source branch failure | Force one source branch to fail | Failure is identifiable; Gold is not accepted solely because master continued |
| ADF-08 | Concurrent execution | Trigger overlapping runs for the same source | No landing collision, checkpoint race, or unintended overwrite |
| ADF-11 | PostgreSQL source branch failure | Force a failure before and during table iteration | Master waits for ADLS to finish; Gold is skipped; notification runs and reports FAILED with the PostgreSQL status |
| ADF-12 | ADLS source branch failure | Force a failure before and during table iteration | Master waits for PostgreSQL to finish; Gold is skipped; notification runs and reports FAILED with the ADLS status |
| ADF-13 | Both source branches fail | Force both source branches to fail | Gold does not run; notification runs once with both source statuses FAILED |
| ADF-14 | Gold failure | Let both source branches succeed, then fail a Gold notebook | Notification runs after the Gold decision and reports FAILED |
| ADF-15 | Empty source metadata | Run a source dispatcher with no active rows for its source_system | Dispatcher fails explicitly rather than succeeding with a zero-iteration ForEach |
| ADF-16 | Empty Gold metadata | Run Gold dispatcher with no active SILVER_TO_GOLD rows | Gold dispatcher fails explicitly rather than reporting successful publication with zero models |
| ADF-17 | Parent failure without table audit row | Force source metadata Lookup failure before audit initialization | Notification subject remains FAILED using parent branch status even if no table-level audit row exists |

**Orchestration gate:** the master waits for both source branches on `Completed`, evaluates their `.Status` values, and invokes Gold only when both are `Succeeded`. The notification pipeline depends on the Gold-decision activity's `Completed` path, so it should still run when one or both source branches fail and Gold is skipped. The email subject must be FAILED whenever a parent branch is not Succeeded or a table-level audit row is non-SUCCESS. Both source-to-Silver and Silver-to-Gold dispatchers must fail closed when the active metadata lookup returns zero rows.

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
| FILE-09 | Empty source folder | Use an existing folder with no CSV files | Zero file iterations; incremental load records NO_DATA/zero rows; FULL fails its source-inventory check |
| FILE-14 | FULL feed already processed | Keep one or more CSV files in the source folder, all already marked PROCESSED, then run the FULL feed again | Run succeeds as a no-op; no landing batch or Silver overwrite occurs; audit reports zero rows |
| FILE-15 | FULL feed contains an empty new file | Add a new empty CSV file version and run the FULL feed | File copies, but zero parsed rows cause Landing-to-Bronze to fail; existing Silver data is not overwritten |
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
| BRZ-12 | Missing/invalid load strategy | Omit load_type or pass an unsupported value | Notebook fails before reading/writing Bronze; it never assumes FULL |
| BRZ-13 | Unsafe identifiers | Pass invalid source_system, table_name, or landing_timestamp values | Notebook rejects parameters before constructing paths or table identifiers |
| BRZ-14 | Reserved metadata columns | Include landing_timestamp or insert_timestamp in the incoming source (including case variants) | Notebook rejects the source before adding operational metadata or writing Bronze |
| BRZ-15 | Case-insensitive source columns | Supply duplicate column names differing only by case | Notebook rejects the incoming schema before target mutation |
| BRZ-16 | Existing Bronze technical schema | Remove/rename a technical metadata column or change its type | Notebook blocks the write and requires a reviewed Bronze migration |
| BRZ-17 | Case-insensitive schema comparison | Change a source column's case without changing its meaning, then separately add/remove/change a field type | Name-only case differences are matched consistently; additions/removals/type drift fail before append |
| BRZ-08 | Schema drift | Add, remove, or change a source field | Drift is detected or handled by explicit policy; no silent incorrect coercion |
| BRZ-09 | ADF no-data status propagation | Run an incremental source that produces no landing records | Landing-to-Bronze returns `NO_DATA`; ADF passes that status to Silver; Silver exits with zero rows; checkpoint remains unchanged; audit records SUCCESS with zero rows |

The current Landing-to-Bronze notebook validates source/table/batch parameters and load strategy, appends non-empty batches with batch/insert timestamps, rejects source columns that collide with reserved technical metadata, and enforces a case-insensitive fail-closed schema contract. It rejects exact same-timestamp batch replay but does not deduplicate identical business records re-extracted under a new batch ID; BRZ-11 remains a key reliability test. Static CI checks the repository/code contract and notebook syntax; the Databricks-specific data scenarios above still require runtime execution.

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
| SLV-12 | Duplicate source keys | Supply two source rows with the same configured merge key | Notebook rejects the batch before target mutation; no arbitrary winner is selected |
| SLV-13 | Null merge key or source version | Supply a null business key or null configured version value | Notebook rejects the batch before target mutation |
| SLV-14 | Late/out-of-order update | Process an older source version after a newer target version | Existing target row remains unchanged; stale-row count is logged |
| SLV-15 | Missing merge metadata | Remove the merge-key column or configured source-version column | Notebook fails before target mutation |
| SLV-16 | Empty MERGE batch | Process an incremental batch with no records | Silver write is skipped; existing target remains unchanged; checkpoint is not advanced |
| SLV-17 | Equal-version replay | Reprocess the same business payload with the same source version | Existing row remains unchanged; no duplicate is inserted |
| SLV-18 | Equal-version conflict | Supply changed business values with the same key and source version | Notebook rejects the batch before MERGE |
| SLV-19 | Invalid existing target | Seed duplicate/null target keys or null target versions | Notebook blocks MERGE and requires target reconciliation |
| SLV-20 | Missing/invalid load strategy | Omit load_type or pass an unsupported value | Notebook fails closed; it never assumes FULL or overwrites Silver |
| SLV-21 | Invalid table/batch identifier | Pass an unsafe table_name or landing_timestamp parameter | Notebook rejects the parameter before constructing Spark identifiers or batch filters |
| SLV-22 | DATA/empty-batch mismatch | Pass landing_status=DATA while the selected Bronze batch has no rows | Notebook fails before Silver mutation and downstream checkpoint success |
| SLV-23 | MERGE payload type drift | Change a non-version source column type while retaining the target schema | Notebook reports the mismatched column types and blocks MERGE before target mutation |
| SLV-24 | Target column-name collision | Seed target columns that collide case-insensitively | Notebook blocks MERGE and requires schema reconciliation |

The shared notebook receives the configured watermark column from active source metadata as its MERGE source-version field. MERGE rejects null or duplicate source keys, null source versions, invalid target keys, case-insensitive column-name collisions, and source/target column-name or data-type mismatches. It updates a matched row only when the incoming version is strictly newer. Equal-version identical business payloads are no-ops; equal-version payload conflicts are rejected. Missing/invalid load strategies fail closed rather than defaulting to FULL. Static CI checks enforce these code/configuration contracts and notebook Python syntax; the Databricks-specific data scenarios above still require execution in a deployed workspace.

## 7. Watermark and checkpoint tests

The current PostgreSQL patients source uses a metadata-configured five-minute lookback. ADF captures a fixed UTC upper bound at the start of the table run and extracts the half-open interval `[previous watermark - lookback, run-start upper bound)`. The checkpoint advances to that captured upper bound only after Silver succeeds; the update is monotonic across overlapping runs.

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| WMR-01 | Initial checkpoint | Run the patients MERGE with the seeded historical watermark and five-minute lookback | Expected source history is selected; the initial extraction window is bounded by the captured run-start upper bound |
| WMR-02 | Successful checkpoint | Complete extraction and Silver processing | Checkpoint equals the captured run-start upper bound, not pipeline completion time; it advances only after required processing succeeds; success audit waits for checkpoint activity success |
| WMR-03 | Failed Silver write | Force Silver notebook failure | Watermark does not advance |
| WMR-04 | Failed checkpoint update | Allow Silver write, then fail checkpoint activity | Target/checkpoint discrepancy is observable and recoverable; success audit is not written and parent failure handling records FAILED |
| WMR-05 | Inclusive lower boundary | Create a source change exactly equal to `previous watermark - lookback` | Row is selected by the `>=` lower-bound predicate and replayed safely through MERGE |
| WMR-06 | Late-arriving update within lookback | Make a source update visible after the previous run's extraction but with `updated_at` inside the configured five-minute overlap | The next run re-reads the record and Silver reflects the newer source version |
| WMR-07 | Late-arriving update outside lookback | Introduce a change whose source timestamp is more than five minutes behind the current checkpoint | Test demonstrates the known limitation: the bounded overlap does not guarantee capture; record the need for a larger source-specific window or CDC |
| WMR-08 | UTC/time-zone consistency | Use source and orchestration timestamps with known offsets; inspect source DDL and incremental fixtures | Source `updated_at` values and ADF bounds use UTC with consistent timestamp precision; no implicit local-time conversion occurs |
| WMR-09 | Null/malformed watermark | Supply an invalid or null checkpoint | Pipeline fails clearly before unsafe query execution |
| WMR-10 | Per-object isolation | Process two incremental objects with different lookback values | Each object's window and checkpoint remain isolated by `table_id` |
| WMR-11 | Checkpoint recovery | Restore a verified prior checkpoint in a disposable environment | Backfill reconciles without silent loss or uncontrolled duplication |
| WMR-12 | Source change after run start | Commit a source update after the first run captures its upper bound | The first run does not advance beyond its captured bound; the next run's interval includes the later update |
| WMR-13 | Overlapping concurrent runs | Run two attempts for the same metadata object with different captured upper bounds and complete the newer run first | Older completion cannot regress the persisted checkpoint; stale source versions cannot overwrite newer Silver values |
| WMR-14 | Lookback replay idempotency | Re-run unchanged patient rows inside the overlap window | Silver retains one row per `patient_id`; equal-version identical payloads are no-ops and conflicts fail |
| WMR-15 | Exclusive upper boundary | Create a source timestamp equal to the captured run-start upper bound | It is excluded from the current half-open window and selected by a subsequent window; no boundary row is lost |
| WMR-16 | Automatic source timestamp maintenance | Update a patient row without explicitly setting `updated_at` | The PostgreSQL trigger assigns a new UTC `updated_at` value; the change becomes eligible in the next bounded extraction window |

**Remaining source-contract limitations:** a five-minute lookback mitigates short visibility delays and modest backdating, but it is not a completeness guarantee. An update arriving later than the window, a change that does not update `updated_at`, a hard delete, or a timestamp anomaly outside the overlap can still be missed. The source DDL and supplied incremental scripts normalize the timestamp-without-time-zone values to UTC; a real source must honor that contract. ADLS CSV selection is manifest-based and does not use `ctrl.watermark`.


## 8. Audit and failure-path tests

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| AUD-01 | Start audit | Start table-stage execution | IN_PROGRESS record is associated with expected ADF run and table |
| AUD-02 | Success audit | Complete notebook, checkpoint control (or valid FULL/no-data skip), and success activity | SUCCESS, end time, and records_written reflect execution; incremental no-data is SUCCESS with zero rows |
| AUD-03 | Failure audit | Force upstream notebook/activity failure | FAILED status identifies table and stage |
| AUD-04 | Audit update failure | Fail audit update after data write and checkpoint success | Data/checkpoint success and audit failure are distinguishable |
| AUD-05 | Stale IN_PROGRESS | Simulate interrupted run | Stale execution is discoverable and reconcilable to ADF history |
| AUD-06 | Multiple runs | Execute same table in separate ADF runs | Audit records associate with correct run |
| AUD-07 | Idempotent audit retry | Start the same table/stage twice using the same parent ADF run ID | One row exists for the natural key; the second start resets status to IN_PROGRESS and clears prior result fields |
| AUD-08 | Stage-scoped updates | Use the same parent run and table ID for SOURCE_TO_SILVER and SILVER_TO_GOLD | Updating one stage does not change the other stage's audit row |
| AUD-09 | Unique-key enforcement | Attempt to create duplicate `(adf_run_id, table_id, stage)` rows | Unique key rejects the duplicate |
| AUD-10 | Existing-history migration precheck | Run migration against a disposable audit table containing duplicate natural keys | Migration stops before creating the unique index and does not delete historical rows |
| AUD-11 | Concurrent upsert | Simulate two attempts to create the same run/table/stage key | HOLDLOCK plus unique index leaves exactly one audit row; losing attempt is surfaced for reconciliation |

## 8A. Notification contract and delivery tests

| ID | Scenario | Test procedure | Acceptance criteria |
|---|---|---|---|
| NOTIF-01 | Successful master run | Run both source branches and Gold successfully | Request contains parent run ID, all three Succeeded statuses, ordered audit rows, and SUCCESS subject |
| NOTIF-02 | Source failure before audit initialization | Fail a source metadata Lookup before table iteration | Request still runs; parent source status is Failed; Gold is SKIPPED_SOURCE_FAILURE; empty status_table is accepted; subject is FAILED |
| NOTIF-03 | Gold failure | Let both source branches succeed and fail one Gold notebook | Request reports source statuses Succeeded, Gold decision Failed, and a FAILED subject |
| NOTIF-04 | Table-level failure | Fail a table stage after its audit row is initialized | status_table contains the scoped FAILED row and failed-count logic produces FAILED |
| NOTIF-05 | External Parse JSON compatibility | Post representative success, source-failure, and empty-status-table payloads to the deployed Logic Apps trigger | The consumer accepts exact field names/types, including legacy email_receipients, and handles an empty array |
| NOTIF-06 | HTTP endpoint failure | Use a disposable invalid endpoint or force a non-success response | Web Activity fails visibly; no false delivery success is reported |
| NOTIF-07 | Endpoint timeout | Use a controlled endpoint that does not respond within the configured response timeout | Web Activity fails at the configured two-minute HTTP response timeout |
| NOTIF-08 | Duplicate request handling | Submit the same adf_run_id twice in a disposable Logic Apps environment | Receiver-side deduplication prevents duplicate email delivery before automatic retries or manual redelivery are enabled |
| NOTIF-09 | Mailbox delivery confirmation | Complete a test Logic Apps run to an approved test recipient | Logic Apps run and email action succeed; delivery is verified independently of ADF HTTP acknowledgement |

The producer-side JSON structure is statically checked in repository CI. NOTIF-05 through NOTIF-09 require the external Logic Apps workflow and a test recipient; they are not proven by repository CI. The Logic Apps definition is not checked into this repository.


The audit implementation now uses `(adf_run_id, table_id, stage)` as its natural key. Start activities use a `MERGE ... WITH (HOLDLOCK)` upsert, and status updates include the stage. This deliberately retains the latest attempt summary per table/stage/parent run; ADF execution history remains the source for per-attempt detail.

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
| G7A — Notification | Request contract, endpoint acknowledgement, Logic Apps run, and email-action evidence | Failure outcomes are observable and test notifications reach the approved test recipient |
| G8 — Sign-off | Test report, exceptions, owner, run IDs | Critical tests pass or have explicit accepted exception |

## 12. Sign-off record

Record release/deployment identifier, workspace/environment, test date, ADF run IDs, test IDs passed/failed/blocked, known exceptions, reconciliation evidence, checkpoint values, reviewer, and approval decision.

A test is PASS only when its acceptance criteria are supported by captured evidence. A test case, static code review, or historical successful execution does not prove that a new deployment or code change has passed that test.
