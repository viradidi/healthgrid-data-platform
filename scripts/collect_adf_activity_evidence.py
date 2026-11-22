#!/usr/bin/env python3
"""Collect a sanitized Azure Data Factory activity-run summary for HealthGrid.

Only allow-listed execution metadata is written to the evidence file. Raw ADF
activity inputs and outputs are deliberately excluded because they may contain
deployment parameters or connection details.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REQUIRED_SOURCE_ACTIVITIES = (
    "Source to Silver Postgres",
    "Source to Silver ADLS csv",
)
GOLD_NOTEBOOK_ACTIVITY = "Silver to Gold"
GOLD_AUDIT_ACTIVITY = "Update Success Status"
EXPECTED_GOLD_OUTPUTS = 3


def _walk_pipeline_run_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() == "pipelinerunid" and isinstance(child, str) and child.strip():
                found.add(child.strip())
            found.update(_walk_pipeline_run_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_walk_pipeline_run_ids(child))
    return found


def discover_child_pipeline_run_ids(activity_runs: list[dict[str, Any]]) -> set[str]:
    """Find child pipeline run IDs in ExecutePipeline activity outputs."""
    found: set[str] = set()
    for activity in activity_runs:
        found.update(_walk_pipeline_run_ids(activity.get("output", {})))
    return found


def _row_count(output: Any) -> int | None:
    if not isinstance(output, dict):
        return None
    value = output.get("runOutput")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.isdigit():
            return int(candidate)
    return None


def sanitize_activity(activity: dict[str, Any], parent_pipeline_run_id: str) -> dict[str, Any]:
    """Return execution metadata only; never persist raw input/output payloads."""
    output = activity.get("output", {})
    return {
        "parent_pipeline_run_id": parent_pipeline_run_id,
        "activity_name": activity.get("activityName"),
        "activity_type": activity.get("activityType"),
        "status": activity.get("status"),
        "activity_run_id": activity.get("activityRunId"),
        "run_start": activity.get("activityRunStart"),
        "run_end": activity.get("activityRunEnd"),
        "duration_ms": activity.get("durationInMs"),
        "notebook_row_count": _row_count(output),
        "child_pipeline_run_ids": sorted(_walk_pipeline_run_ids(output)),
    }


def verify_activity_evidence(
    activity_runs: list[dict[str, Any]],
    root_pipeline_run_id: str,
) -> list[str]:
    """Fail closed unless both source branches and all current Gold outputs ran."""
    errors: list[str] = []
    root = [
        item for item in activity_runs
        if item.get("parent_pipeline_run_id") == root_pipeline_run_id
    ]

    for required_name in REQUIRED_SOURCE_ACTIVITIES:
        matching = [item for item in root if item.get("activity_name") == required_name]
        if not matching:
            errors.append(f"Missing master-pipeline activity: {required_name}.")
        elif any(item.get("status") != "Succeeded" for item in matching):
            statuses = ", ".join(str(item.get("status")) for item in matching)
            errors.append(f"{required_name} did not succeed (observed: {statuses}).")

    gold = [
        item for item in activity_runs
        if item.get("activity_name") == GOLD_NOTEBOOK_ACTIVITY
    ]
    gold_successes = [item for item in gold if item.get("status") == "Succeeded"]
    if len(gold_successes) < EXPECTED_GOLD_OUTPUTS:
        errors.append(
            f"Expected at least {EXPECTED_GOLD_OUTPUTS} successful Gold notebook "
            f"activities; found {len(gold_successes)}."
        )
    if any(item.get("status") != "Succeeded" for item in gold):
        errors.append("One or more Gold notebook activities did not succeed.")

    audit_updates = [
        item for item in activity_runs
        if item.get("activity_name") == GOLD_AUDIT_ACTIVITY
    ]
    audit_successes = [item for item in audit_updates if item.get("status") == "Succeeded"]
    if len(audit_successes) < EXPECTED_GOLD_OUTPUTS:
        errors.append(
            f"Expected at least {EXPECTED_GOLD_OUTPUTS} successful Gold audit updates; "
            f"found {len(audit_successes)}."
        )
    if any(item.get("status") != "Succeeded" for item in audit_updates):
        errors.append("One or more Gold audit-update activities did not succeed.")

    return errors


def _az_json(arguments: list[str]) -> Any:
    command = ["az", *arguments, "--only-show-errors", "--output", "json"]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def query_pipeline_activities(
    resource_group: str,
    factory_name: str,
    pipeline_run_id: str,
    last_updated_after: str,
    last_updated_before: str,
) -> list[dict[str, Any]]:
    response = _az_json([
        "datafactory", "activity-run", "query-by-pipeline-run",
        "--resource-group", resource_group,
        "--factory-name", factory_name,
        "--run-id", pipeline_run_id,
        "--last-updated-after", last_updated_after,
        "--last-updated-before", last_updated_before,
    ])
    if isinstance(response, dict):
        value = response.get("value", [])
    else:
        value = response
    if not isinstance(value, list):
        raise RuntimeError(f"Unexpected ADF activity-run response for pipeline run {pipeline_run_id}.")
    return [item for item in value if isinstance(item, dict)]


def collect_evidence(
    resource_group: str,
    factory_name: str,
    root_pipeline_run_id: str,
    lookback_hours: int = 12,
    max_pipeline_runs: int = 30,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    after = (now - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    before = (now + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    queue = [root_pipeline_run_id]
    queried: set[str] = set()
    sanitized: list[dict[str, Any]] = []

    while queue:
        current = queue.pop(0)
        if current in queried:
            continue
        if len(queried) >= max_pipeline_runs:
            raise RuntimeError(
                f"Exceeded the safety limit of {max_pipeline_runs} nested ADF pipeline runs."
            )
        queried.add(current)
        rows = query_pipeline_activities(
            resource_group, factory_name, current, after, before
        )
        for row in rows:
            sanitized.append(sanitize_activity(row, current))
        for child_id in sorted(discover_child_pipeline_run_ids(rows)):
            if child_id not in queried and child_id not in queue:
                queue.append(child_id)

    errors = verify_activity_evidence(sanitized, root_pipeline_run_id)
    return {
        "evidence_schema_version": 1,
        "collected_at_utc": now.isoformat(),
        "resource_group": resource_group,
        "data_factory": factory_name,
        "root_pipeline_run_id": root_pipeline_run_id,
        "queried_pipeline_run_ids": sorted(queried),
        "activity_count": len(sanitized),
        "activities": sanitized,
        "acceptance_check": "PASS" if not errors else "FAIL",
        "acceptance_errors": errors,
        "scope_note": (
            "Sanitized ADF activity metadata only. Inspect ctrl.audit_log, "
            "watermarks, file manifest and the Gold tables separately before "
            "signing off full runtime acceptance."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--factory-name", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lookback-hours", type=int, default=12)
    args = parser.parse_args()

    try:
        evidence = collect_evidence(
            args.resource_group,
            args.factory_name,
            args.run_id,
            lookback_hours=args.lookback_hours,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"Collected {evidence['activity_count']} sanitized activity records "
            f"across {len(evidence['queried_pipeline_run_ids'])} pipeline run(s)."
        )
        print(f"Activity evidence acceptance check: {evidence['acceptance_check']}")
        for error in evidence["acceptance_errors"]:
            print(f"ERROR: {error}")
        return 0 if evidence["acceptance_check"] == "PASS" else 1
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
