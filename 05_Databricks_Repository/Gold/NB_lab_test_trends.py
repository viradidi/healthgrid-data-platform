# Databricks notebook source
# DBTITLE 1,Lab Test Trends Overview
# MAGIC %md
# MAGIC # NB_lab_test_trends
# MAGIC
# MAGIC Builds `adb_caresync.gold.lab_test_trends` from monthly lab-result aggregates with optional calendar enrichment, then validates month-over-month trend columns and sample output.

# COMMAND ----------

# DBTITLE 1,Create lab test trends gold table
# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS adb_caresync.gold;
# MAGIC
# MAGIC CREATE OR REPLACE TABLE adb_caresync.gold.lab_test_trends AS
# MAGIC WITH monthly_metrics AS (
# MAGIC   SELECT
# MAGIC     test_name,
# MAGIC     year(test_date) AS year,
# MAGIC     month(test_date) AS month,
# MAGIC     date_trunc('month', test_date) AS month_start_date,
# MAGIC     CAST(COUNT(*) AS INT) AS total_tests,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Abnormal' THEN 1 ELSE 0 END) AS INT) AS abnormal_test_count,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Critical' THEN 1 ELSE 0 END) AS INT) AS critical_test_count
# MAGIC   FROM adb_caresync.silver.lab_results
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
# MAGIC   LEFT JOIN adb_caresync.silver.calendar AS c
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

# DBTITLE 1,Return lab test trends record count
updated_df = spark.table("adb_caresync.gold.lab_test_trends")
record_count = updated_df.count()
dbutils.notebook.exit(str(record_count))