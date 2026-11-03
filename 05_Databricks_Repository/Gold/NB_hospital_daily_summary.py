# Databricks notebook source
# DBTITLE 1,Hospital Daily Summary Overview
# MAGIC %md
# MAGIC # NB_hospital_daily_summary
# MAGIC
# MAGIC Builds `healthgrid.gold.hospital_daily_summary` and validates its schema, hospital/date grain, and metric bounds.

# COMMAND ----------

# DBTITLE 1,Validate hospital event and calendar relationships
from pyspark.sql import functions as F

lab_source = spark.table("healthgrid.silver.lab_results")
hospitals_source = spark.table("healthgrid.silver.hospitals")
doctors_source = spark.table("healthgrid.silver.doctors")
calendar_source = spark.table("healthgrid.silver.calendar")

def assert_unique_non_null_key(dataframe, key, label):
    if dataframe.filter(F.col(key).isNull()).limit(1).count():
        raise ValueError(f"{label}.{key} contains NULL values.")
    duplicates = (
        dataframe.groupBy(key)
        .count()
        .filter(F.col("count") > 1)
        .limit(1)
        .count()
    )
    if duplicates:
        raise ValueError(f"{label}.{key} is not unique; Gold join cardinality is unsafe.")

assert_unique_non_null_key(lab_source, "lab_result_id", "lab_results")
assert_unique_non_null_key(hospitals_source, "hospital_id", "hospitals")
assert_unique_non_null_key(doctors_source, "doctor_id", "doctors")
assert_unique_non_null_key(calendar_source, "date_key", "calendar")

allowed_statuses = ["Normal", "Abnormal", "Critical"]
invalid_lab_events = lab_source.filter(
    F.col("hospital_id").isNull()
    | F.col("doctor_id").isNull()
    | F.col("test_date").isNull()
    | F.col("result_status").isNull()
    | (~F.col("result_status").isin(allowed_statuses))
).limit(1).count()
if invalid_lab_events:
    raise ValueError("lab_results contains a NULL hospital/doctor/date/status or unsupported result_status.")

orphan_hospital_events = (
    lab_source.select("hospital_id").distinct()
    .join(hospitals_source.select("hospital_id"), on="hospital_id", how="left_anti")
    .limit(1).count()
)
if orphan_hospital_events:
    raise ValueError("lab_results contains hospital_id values missing from Silver hospitals.")

orphan_doctor_events = (
    lab_source.select("doctor_id").distinct()
    .join(doctors_source.select("doctor_id"), on="doctor_id", how="left_anti")
    .limit(1).count()
)
if orphan_doctor_events:
    raise ValueError("lab_results contains doctor_id values missing from Silver doctors.")

event_dates = lab_source.select(F.to_date("test_date").alias("event_date")).distinct()
calendar_dates = calendar_source.select(F.to_date("date").alias("event_date")).distinct()
missing_calendar_dates = (
    event_dates.join(calendar_dates, on="event_date", how="left_anti")
    .limit(1).count()
)
if missing_calendar_dates:
    raise ValueError("Silver calendar does not cover every laboratory test_date used by hospital daily reporting.")

# COMMAND ----------

# DBTITLE 1,Create hospital daily summary gold table
# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS healthgrid.gold;
# MAGIC
# MAGIC CREATE OR REPLACE TABLE healthgrid.gold.hospital_daily_summary AS
# MAGIC WITH daily_metrics AS (
# MAGIC   SELECT
# MAGIC     hospital_id,
# MAGIC     test_date AS summary_date,
# MAGIC     CAST(COUNT(*) AS INT) AS total_tests,
# MAGIC     CAST(COUNT(DISTINCT patient_id) AS INT) AS unique_patients_tested,
# MAGIC     CAST(COUNT(DISTINCT doctor_id) AS INT) AS active_doctor_count,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Abnormal' THEN 1 ELSE 0 END) AS INT) AS abnormal_test_count,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Critical' THEN 1 ELSE 0 END) AS INT) AS critical_test_count
# MAGIC   FROM healthgrid.silver.lab_results
# MAGIC   GROUP BY hospital_id, test_date
# MAGIC ),
# MAGIC enriched AS (
# MAGIC   SELECT
# MAGIC     dm.hospital_id,
# MAGIC     h.hospital_name,
# MAGIC     dm.summary_date,
# MAGIC     c.day_name,
# MAGIC     c.is_weekend,
# MAGIC     dm.total_tests,
# MAGIC     dm.unique_patients_tested,
# MAGIC     dm.active_doctor_count,
# MAGIC     dm.abnormal_test_count,
# MAGIC     dm.critical_test_count,
# MAGIC     CAST(CASE WHEN dm.total_tests = 0 THEN NULL ELSE ROUND(dm.abnormal_test_count * 100.0 / dm.total_tests, 2) END AS DECIMAL(5,2)) AS abnormal_rate_pct,
# MAGIC     CAST(CASE WHEN dm.total_tests = 0 THEN NULL ELSE ROUND(dm.critical_test_count * 100.0 / dm.total_tests, 2) END AS DECIMAL(5,2)) AS critical_rate_pct
# MAGIC   FROM daily_metrics AS dm
# MAGIC   LEFT JOIN healthgrid.silver.hospitals AS h
# MAGIC     ON dm.hospital_id = h.hospital_id
# MAGIC   LEFT JOIN healthgrid.silver.calendar AS c
# MAGIC     ON CAST(date_format(dm.summary_date, 'yyyyMMdd') AS INT) = c.date_key
# MAGIC )
# MAGIC SELECT
# MAGIC   hospital_id,
# MAGIC   hospital_name,
# MAGIC   summary_date,
# MAGIC   day_name,
# MAGIC   is_weekend,
# MAGIC   total_tests,
# MAGIC   unique_patients_tested,
# MAGIC   active_doctor_count,
# MAGIC   abnormal_test_count,
# MAGIC   critical_test_count,
# MAGIC   abnormal_rate_pct,
# MAGIC   critical_rate_pct,
# MAGIC   CAST(LAG(total_tests) OVER (PARTITION BY hospital_id ORDER BY summary_date) AS INT) AS prev_day_total_tests,
# MAGIC   CAST(
# MAGIC     CASE
# MAGIC       WHEN LAG(total_tests) OVER (PARTITION BY hospital_id ORDER BY summary_date) IS NULL
# MAGIC         OR LAG(total_tests) OVER (PARTITION BY hospital_id ORDER BY summary_date) = 0 THEN NULL
# MAGIC       ELSE ROUND(
# MAGIC         (total_tests - LAG(total_tests) OVER (PARTITION BY hospital_id ORDER BY summary_date)) * 100.0
# MAGIC         / LAG(total_tests) OVER (PARTITION BY hospital_id ORDER BY summary_date),
# MAGIC         2
# MAGIC       )
# MAGIC     END AS DECIMAL(6,2)
# MAGIC   ) AS test_volume_change_pct
# MAGIC FROM enriched;

# COMMAND ----------

# DBTITLE 1,Validate hospital daily summary output contract
from pyspark.sql import functions as F

updated_df = spark.table("healthgrid.gold.hospital_daily_summary")
record_count = updated_df.count()

required_columns = {
    "hospital_id", "hospital_name", "summary_date", "day_name", "is_weekend",
    "total_tests", "unique_patients_tested", "active_doctor_count",
    "abnormal_test_count", "critical_test_count", "abnormal_rate_pct",
    "critical_rate_pct", "prev_day_total_tests", "test_volume_change_pct",
}
missing_columns = sorted(required_columns - set(updated_df.columns))
if missing_columns:
    raise ValueError(f"hospital_daily_summary is missing required columns: {missing_columns}")

if updated_df.filter(
    F.col("hospital_name").isNull() | F.col("day_name").isNull() | F.col("is_weekend").isNull()
).limit(1).count():
    raise ValueError("hospital_daily_summary contains unresolved hospital or calendar enrichment.")

if updated_df.filter(
    F.col("hospital_id").isNull() | F.col("summary_date").isNull()
).limit(1).count():
    raise ValueError("hospital_daily_summary contains a null grain key.")

duplicate_hospital_day = (
    updated_df.groupBy("hospital_id", "summary_date")
    .count()
    .filter(F.col("count") > 1)
    .limit(1)
    .count()
)
if duplicate_hospital_day:
    raise ValueError("hospital_daily_summary violates its one-row-per-hospital/date grain.")

invalid_metrics = updated_df.filter(
    (F.col("total_tests") < 0)
    | (F.col("unique_patients_tested") < 0)
    | (F.col("unique_patients_tested") > F.col("total_tests"))
    | (F.col("active_doctor_count") < 0)
    | (F.col("active_doctor_count") > F.col("total_tests"))
    | (F.col("abnormal_test_count") < 0)
    | (F.col("abnormal_test_count") > F.col("total_tests"))
    | (F.col("critical_test_count") < 0)
    | (F.col("critical_test_count") > F.col("total_tests"))
    | (F.col("abnormal_rate_pct").isNotNull() & ((F.col("abnormal_rate_pct") < 0) | (F.col("abnormal_rate_pct") > 100)))
    | (F.col("critical_rate_pct").isNotNull() & ((F.col("critical_rate_pct") < 0) | (F.col("critical_rate_pct") > 100)))
).limit(1).count()
if invalid_metrics:
    raise ValueError("hospital_daily_summary contains invalid counts or rate percentages.")

print(f"[PASS] hospital_daily_summary schema, grain, and metric checks; rows={record_count}")
dbutils.notebook.exit(str(record_count))
