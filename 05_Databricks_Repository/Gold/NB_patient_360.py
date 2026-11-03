# Databricks notebook source
# DBTITLE 1,Patient 360 Overview
# MAGIC %md
# MAGIC # NB_patient_360
# MAGIC
# MAGIC Builds `healthgrid.gold.patient_360` and validates its output schema, patient grain, and count consistency.

# COMMAND ----------

# DBTITLE 1,Validate patient and laboratory source relationships
from pyspark.sql import functions as F

patients_source = spark.table("healthgrid.silver.patients")
hospitals_source = spark.table("healthgrid.silver.hospitals")
providers_source = spark.table("healthgrid.silver.insurance_providers")
lab_source = spark.table("healthgrid.silver.lab_results")

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

assert_unique_non_null_key(patients_source, "patient_id", "patients")
assert_unique_non_null_key(hospitals_source, "hospital_id", "hospitals")
assert_unique_non_null_key(providers_source, "insurance_provider_id", "insurance_providers")
assert_unique_non_null_key(lab_source, "lab_result_id", "lab_results")

allowed_statuses = ["Normal", "Abnormal", "Critical"]
invalid_lab_events = lab_source.filter(
    F.col("patient_id").isNull()
    | F.col("test_date").isNull()
    | F.col("result_status").isNull()
    | (~F.col("result_status").isin(allowed_statuses))
).limit(1).count()
if invalid_lab_events:
    raise ValueError("lab_results contains a NULL patient/date/status or unsupported result_status.")

orphan_patient_events = (
    lab_source.select("patient_id").distinct()
    .join(patients_source.select("patient_id"), on="patient_id", how="left_anti")
    .limit(1).count()
)
if orphan_patient_events:
    raise ValueError("lab_results contains patient_id values missing from Silver patients.")

orphan_hospital_refs = (
    patients_source
    .filter(F.col("registered_hospital_id").isNotNull())
    .select(F.col("registered_hospital_id").alias("hospital_id"))
    .distinct()
    .join(hospitals_source.select("hospital_id"), on="hospital_id", how="left_anti")
    .limit(1).count()
)
if orphan_hospital_refs:
    raise ValueError("patients contains registered_hospital_id values missing from Silver hospitals.")

orphan_provider_refs = (
    patients_source
    .filter(F.col("insurance_provider_id").isNotNull())
    .select("insurance_provider_id").distinct()
    .join(providers_source.select("insurance_provider_id"), on="insurance_provider_id", how="left_anti")
    .limit(1).count()
)
if orphan_provider_refs:
    raise ValueError("patients contains insurance_provider_id values missing from the Silver partner feed.")

# COMMAND ----------
# COMMAND ----------

# DBTITLE 1,Create patient 360 gold table
# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS healthgrid.gold;
# MAGIC
# MAGIC CREATE OR REPLACE TABLE healthgrid.gold.patient_360 AS
# MAGIC WITH lab_results_agg AS (
# MAGIC   SELECT
# MAGIC     patient_id,
# MAGIC     CAST(COUNT(*) AS INT) AS total_tests,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Abnormal' THEN 1 ELSE 0 END) AS INT) AS abnormal_test_count,
# MAGIC     CAST(SUM(CASE WHEN result_status = 'Critical' THEN 1 ELSE 0 END) AS INT) AS critical_test_count,
# MAGIC     MAX(test_date) AS last_test_date
# MAGIC   FROM healthgrid.silver.lab_results
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
# MAGIC FROM healthgrid.silver.patients AS p
# MAGIC LEFT JOIN healthgrid.silver.hospitals AS h
# MAGIC   ON p.registered_hospital_id = h.hospital_id
# MAGIC LEFT JOIN healthgrid.silver.insurance_providers AS ip
# MAGIC   ON p.insurance_provider_id = ip.insurance_provider_id
# MAGIC LEFT JOIN lab_results_agg AS lra
# MAGIC   ON p.patient_id = lra.patient_id;

# COMMAND ----------

# DBTITLE 1,Validate patient 360 output contract
from pyspark.sql import functions as F

updated_df = spark.table("healthgrid.gold.patient_360")
record_count = updated_df.count()

required_columns = {
    "patient_id", "first_name", "last_name", "date_of_birth", "age",
    "gender", "city", "state", "hospital_id", "hospital_name",
    "insurance_provider_id", "insurance_provider_name", "total_tests",
    "abnormal_test_count", "critical_test_count", "last_test_date",
}
missing_columns = sorted(required_columns - set(updated_df.columns))
if missing_columns:
    raise ValueError(f"patient_360 is missing required columns: {missing_columns}")

if updated_df.filter(
    (F.col("hospital_id").isNotNull() & F.col("hospital_name").isNull())
    | (F.col("insurance_provider_id").isNotNull() & F.col("insurance_provider_name").isNull())
).limit(1).count():
    raise ValueError("patient_360 contains unresolved non-null hospital or insurance-provider references.")

if updated_df.filter(F.col("patient_id").isNull()).limit(1).count():
    raise ValueError("patient_360 contains a null patient_id.")

duplicate_patient = (
    updated_df.groupBy("patient_id")
    .count()
    .filter(F.col("count") > 1)
    .limit(1)
    .count()
)
if duplicate_patient:
    raise ValueError("patient_360 violates its one-row-per-patient grain.")

invalid_counts = updated_df.filter(
    (F.col("total_tests") < 0)
    | (F.col("abnormal_test_count") < 0)
    | (F.col("critical_test_count") < 0)
    | (F.col("abnormal_test_count") > F.col("total_tests"))
    | (F.col("critical_test_count") > F.col("total_tests"))
).limit(1).count()
if invalid_counts:
    raise ValueError("patient_360 contains invalid laboratory activity counts.")

print(f"[PASS] patient_360 schema, grain, and metric checks; rows={record_count}")
dbutils.notebook.exit(str(record_count))
