# 🎯 Lead-to-Enrollment Funnel & Marketing Attribution Analytics Platform

An enterprise-grade, end-to-end analytics engineering and machine learning pipeline that models multi-touch marketing attribution, automates star-schema warehousing in Oracle Database, scores prospect conversion propensity via Gradient Boosting, and serves interactive BI dashboards through Streamlit and Tableau.

---

## 📌 Executive Architecture & Data Flow

[Raw CRM Leads]  ──▶  [1. Clean & Validate]  ──▶  [2. Synthesize Multi-Touch & Spend]
│
▼
[Streamlit App]  ◀──  [6. Tableau Extracts]  ◀──  [3. Oracle DB ETL (FREEPDB1)]
▲                      ▲                                │
│                      │                                ▼
[Interactive UI] ◀──  [5. ML Lead Scoring]  ◀──  [4. Feature Engineering]
(Gradient Boosting)


1. **Synthetic Data Synthesis & DQ**: Emulates multi-touch lead journeys across paid and organic channels (Google Ads, Meta Ads, YouTube Ads, Microsoft Ads), deliberately injecting and resolving realistic defects (case inconsistency, missing UTM campaign parameters, orphaned touches, duplicate rows).
2. **Star-Schema Warehousing (Oracle)**: Loads dimensions (`dim_channel`, `dim_course`, `dim_campaign`) and transaction facts (`fact_leads`, `fact_touchpoints`, `fact_spend`) into Oracle `FREEPDB1` via `python-oracledb`.
3. **Analytical View Layer**: Oracle SQL analytical views dynamically calculate:
   - First-Touch, Last-Touch, Linear, and Position-Based (40-20-40) attribution models.
   - Stage-by-stage funnel conversion drop-offs.
   - 30/60/90-day cohort velocity from lead creation to enrollment.
4. **Machine Learning Propensity Engine**: Implements a baseline Logistic Regression and a challenger Gradient Boosting classifier to score leads (0.0 to 1.0) and generate decile lift distributions.
5. **Dual Visualization Presentation Layer**: Automated CSV export extracts serve both Tableau Desktop workbooks (`.twb`) and a multi-tab Streamlit web application.

---

## 🚀 Key Results & Performance Metrics

- **Pipeline Execution Speed**: Full end-to-end automation executes in **~6.2 seconds**.
- **Model Performance**:
  - Baseline Logistic Regression ROC-AUC: **0.8359** | PR-AUC: **0.7657**
  - Challenger Gradient Boosting ROC-AUC: **0.8443** | PR-AUC: **0.7871**
- **Decile Lift**: Decile 1 achieves a **92.43% conversion rate** (**2.40x baseline lift**), capturing 24.0% of all conversions in the top 10% of leads.
- **Top Conversion Drivers**:
  1. `last_activity_SMS Sent` (20.16% relative importance)
  2. `lead_origin_Lead Add Form` (19.09% relative importance)
  3. `current_occupation_Working Professional` (12.55% relative importance)

---

## 🛠️ Tech Stack & Requirements

- **Operating System**: macOS (Apple Silicon / Intel) or Linux
- **Language**: Python 3.10+ (tested on Python 3.14)
- **Database**: Oracle Database 23ai / 21c (Thin mode via `oracledb`)
- **Libraries**: `pandas`, `numpy`, `scikit-learn`, `streamlit`, `oracledb`
- **BI / Presentation**: Tableau Desktop, Streamlit

---

## 📁 Repository Structure

├── automate_all.sh                 # Master one-click orchestrator (DB reset, ETL, ML, UI)
├── run_pipeline.py                 # Core analytical pipeline runner
├── config/
│   ├── database.env                # Oracle connection parameters
│   └── channel_mapping.csv         # UTM parameter to channel group rules
├── data/
│   ├── raw/                        # Source Kaggle CRM Leads dataset
│   ├── synthetic/                  # Synthesized touchpoint logs & spend CSVs
│   ├── processed/                  # Feature engineered files & scored leads
│   └── tableau_exports/            # Populated CSV views consumed by BI & Streamlit
├── dashboards/
│   ├── app.py                      # Interactive 4-tab Streamlit dashboard
│   └── funnel_attribution_analytics.twb # Tableau Desktop visualization workbook
├── sql/
│   ├── schema.sql                  # Oracle DDL for dimensions and facts
│   └── views.sql                   # Analytical attribution & funnel view queries
└── src/
├── data_cleaning.py            # Stage 1: Validation and duplicate handling
├── touchpoint_synthesis.py     # Stage 2: Multi-touch and daily spend generation
├── etl_load.py                 # Stage 3: Oracle star-schema loader
├── patch_features.py           # Stage 4: Feature transformation for ML
├── lead_scoring.py             # Stage 5: Logistic Regression & Gradient Boosting
└── export_tableau_data.py      # Stage 6: SQL view export to CSV extracts


---

## ⚙️ Configuration & Database Setup

1. **Set Environment Variables**:
   Create or verify `config/database.env`:
   ```bash
   FUNNEL_DB_USER=funnel_prj
   FUNNEL_DB_PASSWORD=your_password
   FUNNEL_DB_DSN=localhost:1521/FREEPDB1
Set up Virtual Environment:

Bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
⚡ Quickstart & Automated Execution
Option A: The One-Click Orchestrator (Recommended)
Place your raw leads file into data/raw/ (e.g., data/raw/leads.csv) and run:

Bash
./automate_all.sh
This script automatically:

Resets warehouse fact tables to prevent primary key / unique constraint collisions.

Generates touchpoints and validates UTM data.

Populates the Oracle star-schema warehouse.

Trains baseline and challenger scoring models.

Generates all Tableau and Streamlit export extracts into data/tableau_exports/.

Launches the Streamlit dashboard on http://localhost:8501.

Option B: Step-by-Step Pipeline Execution
Bash
# 1. Run core pipeline
python run_pipeline.py

# 2. Launch Streamlit analytics dashboard
streamlit run dashboards/app.py
📊 Dashboard Modules (Streamlit & Tableau)
Attribution Comparison: Side-by-side First-Touch vs. Last-Touch vs. Linear attribution models calculating true CAC, ROAS, and attributed channel revenue.

Lead Scoring & Decile Lift: Operationalized prospect ranking showing conversion probability curves, decile distributions, and SHAP/Gini feature importances.

Daily Channel KPIs: Executive KPI summary cards (Total Spend, Impressions, Clicks) with granular daily channel log explorer.

Funnel Stage Drop-Off: Stage-by-stage drop-off tracking from Captured to Contacted to Qualified grouped by specialization.
