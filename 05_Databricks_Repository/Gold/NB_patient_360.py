# Databricks notebook source
# DBTITLE 1,Patient 360 Overview
# MAGIC %md
# MAGIC # NB_patient_360
# MAGIC
# MAGIC Builds `adb_caresync.gold.patient_360` from the silver patient, hospital, insurance, and lab result tables defined in the STTM workbook, then validates the output schema and sample rows.

# COMMAND ----------

# DBTITLE 1,Create patient 360 gold table
# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS adb_caresync.gold;
# MAGIC
# MAGIC CREATE OR REPLACE TABLE adb_caresync.gold.patient_360 AS
# MAGIC WITH lab_results_agg AS (
# MAGIC   SELECT
# MAGIC     patient_id,
# MAGIC     CAST(COUNT(*) AS INT) AS total_tests,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Abnormal' THEN 1 ELSE 0 END) AS INT) AS abnormal_test_count,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Critical' THEN 1 ELSE 0 END) AS INT) AS critical_test_count,
# MAGIC     MAX(test_date) AS last_test_date
# MAGIC   FROM adb_caresync.silver.lab_results
# MAGIC   GROUP BY patient_id
# MAGIC )
# MAGIC SELECT
# MAGIC   p.patient_id,
# MAGIC   p.first_name,
# MAGIC   p.last_name,
# MAGIC   CAST(p.date_of_birth AS DATE) AS date_of_birth,
# MAGIC   CAST(FLOOR(datediff(current_date(), CAST(p.date_of_birth AS DATE)) / 365.25) AS INT) AS age,
# MAGIC   p.gender,
# MAGIC   p.city,
# MAGIC   p.state,
# MAGIC   p.registered_hospital_id AS hospital_id,
# MAGIC   h.hospital_name,
# MAGIC   p.insurance_provider_id,
# MAGIC   ip.provider_name AS insurance_provider_name,
# MAGIC   COALESCE(lra.total_tests, 0) AS total_tests,
# MAGIC   COALESCE(lra.abnormal_test_count, 0) AS abnormal_test_count,
# MAGIC   COALESCE(lra.critical_test_count, 0) AS critical_test_count,
# MAGIC   lra.last_test_date
# MAGIC FROM adb_caresync.silver.patients AS p
# MAGIC LEFT JOIN adb_caresync.silver.hospitals AS h
# MAGIC   ON p.registered_hospital_id = h.hospital_id
# MAGIC LEFT JOIN adb_caresync.silver.insurance_providers AS ip
# MAGIC   ON p.insurance_provider_id = ip.insurance_provider_id
# MAGIC LEFT JOIN lab_results_agg AS lra
# MAGIC   ON p.patient_id = lra.patient_id;

# COMMAND ----------

# DBTITLE 1,Return patient 360 record count
updated_df = spark.table("adb_caresync.gold.patient_360")
record_count = updated_df.count()
dbutils.notebook.exit(str(record_count))