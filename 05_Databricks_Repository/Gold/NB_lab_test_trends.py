# Databricks notebook source
# DBTITLE 1,Lab Test Trends Overview
# MAGIC %md
# MAGIC # NB_lab_test_trends
# MAGIC
# MAGIC Builds `healthgrid.gold.lab_test_trends` and validates its schema, test/month grain, and metric bounds.

# COMMAND ----------

# DBTITLE 1,Validate test trend event and calendar relationships
from pyspark.sql import functions as F

lab_source = spark.table("healthgrid.silver.lab_results")
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
assert_unique_non_null_key(calendar_source, "date_key", "calendar")

allowed_statuses = ["Normal", "Abnormal", "Critical"]
invalid_lab_events = lab_source.filter(
    F.col("test_name").isNull()
    | F.col("test_date").isNull()
    | F.col("result_status").isNull()
    | (~F.col("result_status").isin(allowed_statuses))
).limit(1).count()
if invalid_lab_events:
    raise ValueError("lab_results contains a NULL test/date/status or unsupported result_status.")

month_starts = lab_source.select(
    F.to_date(F.date_trunc("month", F.col("test_date"))).alias("month_start_date")
).distinct()
calendar_month_starts = calendar_source.select(
    F.to_date("date").alias("month_start_date")
).distinct()
missing_calendar_months = (
    month_starts.join(calendar_month_starts, on="month_start_date", how="left_anti")
    .limit(1).count()
)
if missing_calendar_months:
    raise ValueError("Silver calendar does not cover every month used by lab_test_trends.")

# COMMAND ----------
# COMMAND ----------

# DBTITLE 1,Create lab test trends gold table
# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS healthgrid.gold;
# MAGIC
# MAGIC CREATE OR REPLACE TABLE healthgrid.gold.lab_test_trends AS
# MAGIC WITH monthly_metrics AS (
# MAGIC   SELECT
# MAGIC     test_name,
# MAGIC     year(test_date) AS year,
# MAGIC     month(test_date) AS month,
# MAGIC     date_trunc('month', test_date) AS month_start_date,
# MAGIC     CAST(COUNT(*) AS INT) AS total_tests,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Abnormal' THEN 1 ELSE 0 END) AS INT) AS abnormal_test_count,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Critical' THEN 1 ELSE 0 END) AS INT) AS critical_test_count
# MAGIC   FROM healthgrid.silver.lab_results
# MAGIC   GROUP BY test_name, year(test_date), month(test_date), date_trunc('month', test_date)
# MAGIC ),
# MAGIC enriched AS (
# MAGIC   SELECT
# MAGIC     mm.test_name,
# MAGIC     mm.year,
# MAGIC     mm.month,
# MAGIC     COALESCE(c.month_name, date_format(mm.month_start_date, 'MMMM')) AS month_name,
# MAGIC     CONCAT('Q', quarter(mm.month_start_date)) AS quarter_name,
# MAGIC     mm.total_tests,
# MAGIC     mm.abnormal_test_count,
# MAGIC     mm.critical_test_count,
# MAGIC     CAST(CASE WHEN mm.total_tests = 0 THEN NULL ELSE ROUND(mm.abnormal_test_count * 100.0 / mm.total_tests, 2) END AS DECIMAL(5,2)) AS abnormal_rate_pct,
# MAGIC     CAST(CASE WHEN mm.total_tests = 0 THEN NULL ELSE ROUND(mm.critical_test_count * 100.0 / mm.total_tests, 2) END AS DECIMAL(5,2)) AS critical_rate_pct
# MAGIC   FROM monthly_metrics AS mm
# MAGIC   LEFT JOIN healthgrid.silver.calendar AS c
# MAGIC     ON CAST(date_format(mm.month_start_date, 'yyyyMMdd') AS INT) = c.date_key
# MAGIC )
# MAGIC SELECT
# MAGIC   test_name,
# MAGIC   year,
# MAGIC   month,
# MAGIC   month_name,
# MAGIC   quarter_name,
# MAGIC   total_tests,
# MAGIC   abnormal_test_count,
# MAGIC   critical_test_count,
# MAGIC   abnormal_rate_pct,
# MAGIC   critical_rate_pct,
# MAGIC   CAST(LAG(abnormal_rate_pct) OVER (PARTITION BY test_name ORDER BY year, month) AS DECIMAL(5,2)) AS prev_month_abnormal_rate_pct,
# MAGIC   CAST(
# MAGIC     CASE
# MAGIC       WHEN LAG(abnormal_rate_pct) OVER (PARTITION BY test_name ORDER BY year, month) IS NULL THEN NULL
# MAGIC       ELSE ROUND(
# MAGIC         abnormal_rate_pct - LAG(abnormal_rate_pct) OVER (PARTITION BY test_name ORDER BY year, month),
# MAGIC         2
# MAGIC       )
# MAGIC     END AS DECIMAL(6,2)
# MAGIC   ) AS abnormal_rate_change_pct
# MAGIC FROM enriched;

# COMMAND ----------

# DBTITLE 1,Validate lab test trends output contract
from pyspark.sql import functions as F

updated_df = spark.table("healthgrid.gold.lab_test_trends")
record_count = updated_df.count()

required_columns = {
    "test_name", "year", "month", "month_name", "quarter_name",
    "total_tests", "abnormal_test_count", "critical_test_count",
    "abnormal_rate_pct", "critical_rate_pct",
    "prev_month_abnormal_rate_pct", "abnormal_rate_change_pct",
}
missing_columns = sorted(required_columns - set(updated_df.columns))
if missing_columns:
    raise ValueError(f"lab_test_trends is missing required columns: {missing_columns}")

if updated_df.filter(
    F.col("test_name").isNull()
    | F.col("year").isNull()
    | F.col("month").isNull()
    | (F.col("month") < 1)
    | (F.col("month") > 12)
).limit(1).count():
    raise ValueError("lab_test_trends contains an invalid test/month grain key.")

duplicate_test_month = (
    updated_df.groupBy("test_name", "year", "month")
    .count()
    .filter(F.col("count") > 1)
    .limit(1)
    .count()
)
if duplicate_test_month:
    raise ValueError("lab_test_trends violates its one-row-per-test/month grain.")

invalid_metrics = updated_df.filter(
    (F.col("total_tests") < 0)
    | (F.col("abnormal_test_count") < 0)
    | (F.col("abnormal_test_count") > F.col("total_tests"))
    | (F.col("critical_test_count") < 0)
    | (F.col("critical_test_count") > F.col("total_tests"))
    | (F.col("abnormal_rate_pct").isNotNull() & ((F.col("abnormal_rate_pct") < 0) | (F.col("abnormal_rate_pct") > 100)))
    | (F.col("critical_rate_pct").isNotNull() & ((F.col("critical_rate_pct") < 0) | (F.col("critical_rate_pct") > 100)))
    | (F.col("abnormal_rate_change_pct").isNotNull() & ((F.col("abnormal_rate_change_pct") < -100) | (F.col("abnormal_rate_change_pct") > 100)))
).limit(1).count()
if invalid_metrics:
    raise ValueError("lab_test_trends contains invalid counts, rates, or percentage-point changes.")

print(f"[PASS] lab_test_trends schema, grain, and metric checks; rows={record_count}")
dbutils.notebook.exit(str(record_count))
