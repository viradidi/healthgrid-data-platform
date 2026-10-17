# HealthGrid — Metadata-Driven Healthcare Data Platform

**A cloud data engineering platform for reliable, analytics-ready healthcare data.**

HealthGrid is a fictional healthcare data engineering project developed in an educational setting using synthetic data. It demonstrates how relational hospital data and external partner feeds can be integrated and transformed using Microsoft Azure and Azure Databricks.

The project focuses on metadata-driven ingestion, incremental processing, medallion architecture, pipeline orchestration, and analytical data preparation.

## Business Problem

Healthcare networks often receive data from disconnected operational systems and external partners. Different data structures, duplicated ingestion logic, and limited pipeline visibility can make data integration and reporting difficult to maintain.

HealthGrid explores a reusable approach to ingesting, standardizing, and preparing these datasets for downstream analytics.

## Architecture

![HealthGrid Data Platform Architecture](assets/architecture-overview.png)

The architecture is organized into five primary stages:

1. **Sources:** PostgreSQL operational data and partner CSV files.
2. **Ingestion and orchestration:** Azure Data Factory pipelines and metadata-driven configuration.
3. **Storage:** Azure Data Lake Storage Gen2.
4. **Transformation:** Azure Databricks, PySpark, and Bronze, Silver, and Gold data layers.
5. **Analytics:** Curated datasets for hospital summaries, laboratory trends, and patient-level analytical views.

SQL metadata and control scripts support ingestion configuration and pipeline auditing. Refer to the repository artifacts for the specific implementation details.

## Technology Stack

- **Cloud:** Microsoft Azure
- **Orchestration:** Azure Data Factory
- **Storage:** Azure Data Lake Storage Gen2
- **Databases:** PostgreSQL, Azure SQL Database
- **Processing:** Azure Databricks, Apache Spark,