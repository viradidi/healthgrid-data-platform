# Databricks notebook source
# DBTITLE 1,Hospital Daily Summary Overview
# MAGIC %md
# MAGIC # NB_hospital_daily_summary
# MAGIC
# MAGIC Builds `adb_caresync.gold.hospital_daily_summary` from silver lab results with hospital and calendar enrichment, then validates daily trends and sample output.

# COMMAND ----------

# DBTITLE 1,Create hospital daily summary gold table
# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS adb_caresync.gold;
# MAGIC
# MAGIC CREATE OR REPLACE TABLE adb_caresync.gold.hospital_daily_summary AS
# MAGIC WITH daily_metrics AS (
# MAGIC   SELECT
# MAGIC     hospital_id,
# MAGIC     test_date AS summary_date,
# MAGIC     CAST(COUNT(*) AS INT) AS total_tests,
# MAGIC     CAST(COUNT(DISTINCT patient_id) AS INT) AS unique_patients_tested,
# MAGIC     CAST(COUNT(DISTINCT doctor_id) AS INT) AS active_doctor_count,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Abnormal' THEN 1 ELSE 0 END) AS INT) AS abnormal_test_count,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Critical' THEN 1 ELSE 0 END) AS INT) AS critical_test_count
# MAGIC   FROM adb_caresync.silver.lab_results
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
# MAGIC   LEFT JOIN adb_caresync.silver.hospitals AS h
# MAGIC     ON dm.hospital_id = h.hospital_id
# MAGIC   LEFT JOIN adb_caresync.silver.calendar AS c
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

# DBTITLE 1,Return hospital daily summary record count
updated_df = spark.table("adb_caresync.gold.hospital_daily_summary")
record_count = updated_df.count()
dbutils.notebook.exit(str(record_count))