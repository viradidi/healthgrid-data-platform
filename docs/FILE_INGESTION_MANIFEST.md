# HealthGrid — CSV File Ingestion Manifest

## Purpose

ADLS CSV feeds are selected by source-file identity rather than a timestamp watermark. This separates file delivery tracking from business event time (for example, the `reported_at` column inside a laboratory results file).

The ADF CSV branch enumerates the configured source folder, filters direct child files to `.csv`, reads each file's metadata, checks the manifest, and copies only file versions that have not reached the `PROCESSED` state.

## Manifest identity

The manifest's unique file-version key is:

`table_id + source_path + source_file_name + source_last_modified + source_file_size + source_content_md5`

The ADF Get Metadata activity reads `size`, `lastModified`, and `contentMD5` for each file. If ADLS does not return a content MD5, the pipeline stores an empty value and relies on path, name, modification time, and size. A replacement that preserves all those attributes cannot be distinguished when MD5 is absent.

## State model

| Status | Meaning | Next action |
|---|---|---|
| `IN_PROGRESS` | Manifest row reserved; copy is not yet confirmed | Inspect the ADF Copy run and landing file before recovery |
| `COPIED` | File exists in the run's landing folder; Bronze/Silver completion is not yet committed to the manifest | Do not automatically copy it again; reconcile the downstream batch |
| `PROCESSED` | The file's run completed Landing-to-Bronze and Bronze-to-Silver successfully | Future runs skip this exact file version |
| `FAILED` | The per-file Copy activity failed and the failure was recorded | Inspect partial target state, then retry after cleanup/reconciliation |

The normal transition is:

`IN_PROGRESS → COPIED → PROCESSED`

A failed copy transitions to `FAILED`. A previously failed version may be attempted again. A previous-run `IN_PROGRESS` or `COPIED` version is deliberately blocked rather than recopied automatically.

## ADF execution flow

1. **List Source CSV Files** uses Get Metadata with `childItems` against the configured `source_path`.
2. **Filter CSV Files** retains direct child items with type `File` and a `.csv` extension.
3. **Read Current File Metadata** reads size, last-modified timestamp, and content MD5 for the individual file.
4. **Check File Manifest** determines whether the exact file version is already `PROCESSED`.
5. **Record File In Progress** reserves the file version in Azure SQL and blocks unresolved previous-run states.
6. **Copy CSV File to Landing** copies the individual file into the current run's timestamped landing folder.
7. **Mark File Copied** records successful file transfer.
8. After Landing-to-Bronze and Bronze-to-Silver succeed, **Mark File Manifest Processed** records `PROCESSED` for all copied files in that table/run.
9. Watermark handling is limited to timestamp-watermarked PostgreSQL sources. ADLS CSV ingestion uses the file manifest.

The dataset `DS_Csv_Binary_File` is parameterized with folder, container, and file name so the Copy activity addresses one source file and preserves its file name in landing.

## Empty folders and no-data behavior

If the configured source folder exists but contains no eligible CSV files, the Filter/ForEach path has zero file iterations. Landing-to-Bronze then returns `NO_DATA` for an incremental load; a FULL load fails closed rather than overwriting Silver with an empty batch.

A missing or inaccessible source folder is not treated as an empty feed: Get Metadata fails so that a path or permission problem remains visible.

## Replay and recovery guarantees

This is a conservative file-level idempotency mechanism, not a distributed exactly-once transaction across ADLS, Azure SQL, and Delta Lake.

- An exact file version already marked `PROCESSED` is skipped.
- A failed file copy can be retried after confirming no partial/ambiguous landing output remains.
- A file left `COPIED` after a downstream failure is not copied again automatically. Inspect the stored `landing_path`, the Bronze batch identified by its landing timestamp, the Silver result, the ADF run, and the watermark. Resume or repair the original batch where possible.
- Only after proving that no downstream data write committed may an operator reset a copied/in-progress file version for a fresh copy.
- If Silver committed but manifest finalization failed, reconcile the Silver batch before changing manifest state. Otherwise a fresh APPEND copy can duplicate records.

Useful inspection query:

```sql
SELECT file_manifest_id, table_id, source_path, source_file_name,
       source_last_modified, source_file_size, source_content_md5,
       status, adf_run_id, landing_path, last_error,
       discovered_timestamp, updated_timestamp, processed_timestamp
FROM ctrl.file_ingestion_manifest
WHERE status <> 'PROCESSED'
ORDER BY updated_timestamp DESC;
```

## File replacement semantics

A changed last-modified value, file size, or content MD5 produces a new manifest identity and is treated as a new file version. For an APPEND target, copying a revised whole-file snapshot can reappend records that also existed in the earlier version. The current feed therefore assumes immutable, additive CSV files.

If a partner overwrites existing files, define a separate policy before production use: immutable delivery names, source-row business-key deduplication, or a staging-and-replace/merge strategy. The manifest alone does not deduplicate rows across different file versions.

## Bootstrap and deployment

The manifest table is created by `02_Metadata Table Queries/create_control_tables.sql` and dropped by the disposable-environment reset script. Do not rerun the reset script against valuable data.

On a clean deployment, the first manifest-driven run treats every source file as unseen and processes the configured initial file set. If enabling this logic against an environment that already has populated Bronze/Silver targets, reconcile prior ingestion history and seed or baseline the manifest before running; otherwise historical files may be ingested again.

## Scale and metadata limitations

Azure Data Factory Get Metadata supports `childItems`, `size`, `lastModified`, and `contentMD5` for ADLS Gen2. Its returned metadata is limited to 4 MB, and a folder metadata request enumerates child items. Partition very large source directories or move to a storage-inventory/event-driven pattern when directory listings approach that limit.

References:
- [Get Metadata activity](https://learn.microsoft.com/azure/data-factory/control-flow-get-metadata-activity)
- [ADLS Gen2 connector](https://learn.microsoft.com/azure/data-factory/connector-azure-data-lake-storage)
