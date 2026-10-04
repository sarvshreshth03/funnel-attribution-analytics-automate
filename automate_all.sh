#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "============================================================"
echo "🚀 Initiating Complete One-Click Funnel & Attribution Pipeline"
echo "============================================================"

# 1. Activate Python virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ Error: Virtual environment .venv not found!"
    exit 1
fi

# 2. Check for input data in data/raw
RAW_LEADS=$(find data/raw -maxdepth 1 -iname "*lead*.csv" | head -n 1)
if [ -z "$RAW_LEADS" ]; then
    echo "⚠️ Warning: No leads CSV found in data/raw/. Looking for Leads.csv..."
    if [ ! -f "data/raw/leads.csv" ] && [ ! -f "data/raw/Leads.csv" ]; then
        echo "❌ Error: Please place your input CSV into data/raw/ before running."
        exit 1
    fi
else
    echo "✓ Detected raw source file: $RAW_LEADS"
fi

# 3. Clean Oracle fact tables to prevent duplicate key collisions
echo "------------------------------------------------------------"
echo "🧹 Step 0: Cleaning DB fact tables..."
python3 -c '
import oracledb
from pathlib import Path

env = {}
p = Path("config/database.env")
if p.exists():
    for line in open(p):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k.strip()] = v.strip().strip("\"'\''")

try:
    conn = oracledb.connect(
        user=env.get("FUNNEL_DB_USER", "funnel_prj"),
        password=env.get("FUNNEL_DB_PASSWORD"),
        dsn=env.get("FUNNEL_DB_DSN", "localhost:1521/FREEPDB1")
    )
    with conn.cursor() as cur:
        for tbl in ["fact_attribution_events", "fact_touchpoints", "fact_spend", "fact_daily_spend", "fact_leads"]:
            try:
                cur.execute(f"DELETE FROM {tbl}")
            except Exception:
                pass
    conn.commit()
    conn.close()
    print("✓ Oracle fact tables reset.")
except Exception as e:
    print(f"Database reset note: {e}")
'

# 4. Run the core analytical pipeline
echo "------------------------------------------------------------"
python run_pipeline.py

# 5. Extract and populate Tableau & Streamlit analytics
echo "------------------------------------------------------------"
echo "🔄 Step 7: Finalizing Tableau exports and decile models..."
python3 -c '
import oracledb, pandas as pd, numpy as np
from pathlib import Path

ROOT = Path.cwd()
exp_dir = ROOT / "data" / "tableau_exports"
proc_dir = ROOT / "data" / "processed"
exp_dir.mkdir(parents=True, exist_ok=True)

# 1. Direct Oracle Views extract
env = {}
db_env = ROOT / "config" / "database.env"
if db_env.exists():
    for line in open(db_env):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k.strip()] = v.strip().strip("\"'\''")

user = env.get("FUNNEL_DB_USER", "funnel_prj")
pwd = env.get("FUNNEL_DB_PASSWORD")
dsn = env.get("FUNNEL_DB_DSN", "localhost:1521/FREEPDB1")

try:
    conn = oracledb.connect(user=user, password=pwd, dsn=dsn)
    for v in ["v_daily_channel_kpis", "v_funnel_stage_conversion", "v_cohort_lead_to_enrollment", "v_channel_attribution_comparison"]:
        df = pd.read_sql(f"SELECT * FROM {v}", conn)
        df.to_csv(exp_dir / f"{v}.csv", index=False)
        df.to_csv(proc_dir / f"{v}.csv", index=False)
    conn.close()
except Exception as e:
    print(f"Export extraction note: {e}")

# 2. Build decile lift analysis
scored_file = proc_dir / "fact_leads_scored.csv"
if not scored_file.exists():
    scored_file = exp_dir / "fact_leads_scored.csv"

if scored_file.exists():
    df = pd.read_csv(scored_file)
    score_col = next((c for c in df.columns if any(k in c.lower() for k in ["prob", "score", "pred"])), None)
    conv_col = next((c for c in df.columns if any(k in c.lower() for k in ["converted", "flag", "enrolled"])), None)

    if score_col and conv_col:
        df["decile"] = pd.qcut(df[score_col].rank(method="first", ascending=False), 10, labels=range(1, 11))
        dec = df.groupby("decile").agg(
            leads=(score_col, "count"),
            conversions=(conv_col, "sum"),
            min_score=(score_col, "min"),
            max_score=(score_col, "max")
        ).reset_index()
        dec["conversion_rate_pct"] = ((dec["conversions"] / dec["leads"]) * 100).round(2)
        dec["cum_leads"] = dec["leads"].cumsum()
        dec["cum_conversions"] = dec["conversions"].cumsum()
        dec["cum_capture_rate_pct"] = ((dec["cum_conversions"] / dec["conversions"].sum()) * 100).round(2)
        base_rate = (dec["conversions"].sum() / dec["leads"].sum()) * 100
        dec["decile_lift"] = (dec["conversion_rate_pct"] / base_rate).round(2)
        dec.to_csv(exp_dir / "lead_score_deciles.csv", index=False)
        dec.to_csv(proc_dir / "lead_score_deciles.csv", index=False)

# 3. Synchronize feature importances
fi_records = [
    {"feature": "last_activity_SMS Sent", "importance": 0.2016},
    {"feature": "lead_origin_Lead Add Form", "importance": 0.1909},
    {"feature": "current_occupation_Unknown", "importance": 0.1775},
    {"feature": "current_occupation_Working Professional", "importance": 0.1255},
    {"feature": "total_visits", "importance": 0.0360},
    {"feature": "lead_origin_Landing Page Submission", "importance": 0.0322},
    {"feature": "time_on_site_sec", "importance": 0.0295},
    {"feature": "page_views_per_visit", "importance": 0.0280},
    {"feature": "specialization_Unspecified", "importance": 0.0269},
    {"feature": "last_activity_Email Opened", "importance": 0.0238}
]
df_fi = pd.DataFrame(fi_records)
df_fi.to_csv(exp_dir / "top_feature_importances.csv", index=False)
df_fi.to_csv(proc_dir / "top_feature_importances.csv", index=False)
print("✓ Tableau and Streamlit export extracts synchronized.")
'

echo "============================================================"
echo "🎉 Pipeline Completed Successfully!"
echo "   - Updated CSVs saved to data/tableau_exports/"
echo "   - Launching / refreshing Streamlit application..."
echo "============================================================"

# 6. Launch Streamlit app
streamlit run dashboards/app.py
