import unittest

from scripts.collect_adf_activity_evidence import (
    discover_child_pipeline_run_ids,
    sanitize_activity,
    verify_activity_evidence,
)


class AdfActivityEvidenceTests(unittest.TestCase):
    def _accepted_fixture(self):
        rows = [
            {"activityName": "Source to Silver Postgres", "status": "Succeeded"},
            {"activityName": "Source to Silver ADLS csv", "status": "Succeeded"},
            {
                "activityName": "Execute Silver to Gold",
                "status": "Succeeded",
                "output": {"pipelineRunId": "gold-pipeline-123"},
            },
        ]
        for index in range(3):
            rows.extend([
                {
                    "activityName": "Silver to Gold",
                    "activityType": "DatabricksNotebook",
                    "status": "Succeeded",
                    "output": {"runOutput": str(100 + index)},
                },
                {"activityName": "Update Success Status", "status": "Succeeded"},
            ])
        return rows

    def test_discovers_nested_pipeline_run_ids(self):
        rows = [{
            "output": {
                "pipelineRunId": "child-1",
                "details": [{"pipelineRunId": "child-2"}],
            }
        }]
        self.assertEqual(
            discover_child_pipeline_run_ids(rows),
            {"child-1", "child-2"},
        )

    def test_sanitizer_does_not_copy_raw_payloads(self):
        row = {
            "activityName": "Silver to Gold",
            "activityType": "DatabricksNotebook",
            "status": "Succeeded",
            "activityRunId": "activity-1",
            "output": {"runOutput": "123", "secret": "must-not-be-written"},
            "input": {"accessToken": "must-not-be-written"},
        }
        sanitized = sanitize_activity(row, "parent-1")
        self.assertEqual(sanitized["notebook_row_count"], 123)
        self.assertNotIn("secret", str(sanitized))
        self.assertNotIn("accessToken", str(sanitized))
        self.assertNotIn("input", sanitized)
        self.assertNotIn("output", sanitized)

    def _sanitize_fixture(self, rows):
        sanitized = []
        for row in rows:
            parent_id = (
                "root-1" if row["activityName"].startswith("Source to Silver")
                else "gold-child-1"
            )
            sanitized.append(sanitize_activity(row, parent_id))
        return sanitized

    def test_accepts_both_source_branches_three_gold_runs_and_audits(self):
        rows = self._sanitize_fixture(self._accepted_fixture())
        self.assertEqual(verify_activity_evidence(rows, "root-1"), [])

    def test_fails_when_a_source_branch_failed(self):
        rows = self._accepted_fixture()
        rows[0]["status"] = "Failed"
        errors = verify_activity_evidence(self._sanitize_fixture(rows), "root-1")
        self.assertTrue(any("Source to Silver Postgres did not succeed" in e for e in errors))

    def test_fails_when_gold_notebooks_are_missing(self):
        rows = self._accepted_fixture()
        rows = [r for r in rows if r["activityName"] != "Silver to Gold"]
        errors = verify_activity_evidence(self._sanitize_fixture(rows), "root-1")
        self.assertTrue(any("successful Gold notebook activities" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
