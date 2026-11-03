# HealthGrid — Notification Payload Contract

## Purpose and implementation boundary

This document describes the request produced by the committed Azure Data Factory (ADF) pipeline `PL_SEND_EMAIL` for its configured Logic Apps HTTP endpoint.

**Important boundary:** the Logic Apps workflow/definition is not included in this repository. This is therefore a producer-side contract derived from the ADF export, not proof that a deployed Logic Apps Parse JSON action, email connector, or recipient mapping matches it. Confirm the consumer schema and delivery behavior in the target Azure environment before enabling notifications.

## Invocation and delivery behavior

- The master pipeline invokes `PL_SEND_EMAIL` after the `Run Gold only when both sources succeed` decision activity reaches `Completed`.
- The request is an HTTP POST with `Content-Type: application/json`.
- The endpoint is configured through the ADF global parameter `logic_apps_url`; the recipient is supplied through `email_receipent`. Populate both through secure deployment configuration. Do not commit live endpoint URLs, signatures, tokens, or recipient values.
- The HTTP response timeout is explicitly set to two minutes. ADF Web Activity's documented default is one minute and its configurable HTTP response timeout has a ten-minute maximum. See the [Microsoft Web Activity reference](https://learn.microsoft.com/azure/data-factory/control-flow-web-activity).
- Automatic Web Activity retries remain disabled (`retry: 0`). Until the receiver deduplicates requests by `adf_run_id`, automatically retrying an ambiguously acknowledged POST could send duplicate notifications.
- A successful Web Activity indicates the endpoint completed its request/response contract; it does not independently prove that an email reached a mailbox. Verify the downstream Logic Apps run and email action in the deployed environment.

## Request fields

| Field | Type | Producer meaning |
|---|---|---|
| `adf_run_id` | string | Parent `PL_MASTER` run ID. Use this as the correlation and future receiver-deduplication key. |
| `subject` | string | Environment plus SUCCESS/FAILED outcome and the HealthGrid master-run label. |
| `email_receipients` | string | Recipient value from the legacy ADF global parameter `email_receipent`. The misspelling is retained for wire compatibility until the external consumer is inspected. |
| `body_header` | string | Human-readable PostgreSQL, ADLS CSV, and Gold stage outcomes. |
| `body_footer` | string | Configured closing text. |
| `pipeline_statuses` | object | Parent branch statuses: `postgres_source_to_silver`, `adls_csv_source_to_silver`, and `gold_stage`. |
| `status_table` | array of objects | Table-level rows from `ctrl.audit_log` for this parent run, ordered by `table_id` then `stage`. May be empty when a branch fails before table iteration creates audit rows. |

### Parent pipeline status values

- `postgres_source_to_silver` and `adls_csv_source_to_silver` carry the corresponding ADF child-activity status, typically `Succeeded` or `Failed`.
- `gold_stage` carries the Gold decision outcome when both source branches succeeded. If either source branch did not succeed, the master passes `SKIPPED_SOURCE_FAILURE`.
- The subject is `SUCCESS` only when all three status parameters are `Succeeded` and the table-level audit failure count is zero. Otherwise it is `FAILED`.

### Table audit rows

The producer explicitly projects these `ctrl.audit_log` columns:

`audit_id`, `adf_run_id`, `table_id`, `stage`, `status`, `records_written`, `start_time`, `end_time`, and `created_timestamp`.

The subject's table-level failure count includes every audit row for the parent run whose status is not `SUCCESS`, including `FAILED` and `IN_PROGRESS`. The audit table is a latest-attempt summary per `(adf_run_id, table_id, stage)`, not a per-retry event history.

## Example request

```json
{
  "adf_run_id": "00000000-0000-0000-0000-000000000000",
  "subject": "DEV | FAILED | HEALTHGRID MASTER RUN",
  "email_receipients": "platform-ops@example.com",
  "body_header": "HealthGrid run status | PostgreSQL source-to-Silver: Succeeded | ADLS CSV source-to-Silver: Failed | Gold stage: SKIPPED_SOURCE_FAILURE. Table-level audit details follow.",
  "body_footer": "For support, contact the platform owner.",
  "pipeline_statuses": {
    "postgres_source_to_silver": "Succeeded",
    "adls_csv_source_to_silver": "Failed",
    "gold_stage": "SKIPPED_SOURCE_FAILURE"
  },
  "status_table": []
}
```

The example recipient and run ID are placeholders. The `status_table` is empty to illustrate a parent-branch failure that occurred before table-level audit initialization.

## Consumer compatibility rules

1. The deployed Logic Apps workflow must parse the root-level `adf_run_id`, `pipeline_statuses`, and `status_table` fields.
2. It must handle an empty `status_table`; parent branch fields are the source of truth for failures that happen before table-level audit initialization.
3. Preserve the legacy `email_receipients` request key until the actual Logic Apps mapping is inspected and deliberately migrated.
4. Use `adf_run_id` as a correlation key. Before enabling automatic retries or manual redelivery, make the receiver idempotent for that key to prevent duplicate emails.
5. Do not treat HTTP acknowledgement as proof of mailbox delivery. Retain the Logic Apps run result and verify its email action.

## Known limitations and deployment validation

- No Logic Apps definition, Parse JSON schema, email action, or receiver-side idempotency implementation is checked into this repository.
- There is no durable notification outbox or independent notification-delivery audit table. If the HTTP call fails, inspect the ADF Web Activity and Logic Apps run history before attempting manual resend.
- The Web Activity currently has no automatic retry. This is deliberate until receiver-side deduplication is implemented.
- The external workflow must be validated with success, source-failure-before-audit, Gold-skipped, table-level-failure, empty-audit-array, invalid-recipient, non-2xx response, and endpoint-timeout scenarios.
- The actual Logic Apps request schema and email delivery have not been runtime-tested because the original cloud environment was decommissioned.
