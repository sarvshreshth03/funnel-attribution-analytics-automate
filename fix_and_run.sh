#!/usr/bin/env bash
set -e

echo "============================================================"
echo "🔧 Applying Permanent Fixes to Funnel Analytics Automation..."
echo "============================================================"

# Navigate to project root
cd ~/Downloads/funnel-attribution-analytics-automate

# 1. Patch src/etl_load.py to explicitly commit transactions after loading facts/dimensions
python3 -c '
from pathlib import Path

etl_path = Path("src/etl_load.py")
if etl_path.exists():
    code = etl_path.read_text()
    
    if "fact_leads = load_fact_leads" in code and "conn.commit()" not in code:
        code = code.replace(
            "fact_leads = load_fact_leads(cur, crm, dim_channel, dim_campaign, dim_course)",
            "fact_leads = load_fact_leads(cur, crm, dim_channel, dim_campaign, dim_course)\n    conn.commit()\n    print(\"Committed fact_leads to Oracle.\")"
        )
        code = code.replace(
            "load_fact_touchpoints(cur, touchpoints, dim_channel, dim_campaign)",
            "load_fact_touchpoints(cur, touchpoints, dim_channel, dim_campaign)\n    conn.commit()\n    print(\"Committed fact_touchpoints to Oracle.\")"
        )
        code = code.replace(
            "load_fact_daily_spend(cur, daily_spend, dim_channel, dim_campaign)",
            "load_fact_daily_spend(cur, daily_spend, dim_channel, dim_campaign)\n    conn.commit()\n    print(\"Committed fact_daily_spend to Oracle.\")"
        )
        etl_path.write_text(code)
        print("✅ Added explicit commits to src/etl_load.py")
    else:
        if "conn.commit()" not in code and "with oracledb.connect" in code:
            lines = code.splitlines()
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if "load_fact_daily_spend" in line:
                    indent = len(line) - len(line.lstrip())
                    new_lines.append(" " * indent + "conn.commit()")
                    new_lines.append(" " * indent + "print(\"Committed all data to Oracle.\")")
            etl_path.write_text("\n".join(new_lines))
            print("✅ Injected conn.commit() after ETL procedures")
'

# 2. Patch src/export_tableau_data.py to export directly into data/tableau_exports/
python3 -c '
from pathlib import Path

export_path = Path("src/export_tableau_data.py")
if export_path.exists():
    code = export_path.read_text()
    code = code.replace("data/processed", "data/tableau_exports")
    code = code.replace("data\" / \"processed", "data\" / \"tableau_exports")
    export_path.write_text(code)
    print("✅ Directed export destination to data/tableau_exports/")
'

# 3. Patch run_pipeline.py to sync any model outputs to data/tableau_exports/
python3 -c '
from pathlib import Path

pipe_path = Path("run_pipeline.py")
if pipe_path.exists():
    code = pipe_path.read_text()
    sync_code = """
    # Sync all generated exports into data/tableau_exports/
    export_dir = BASE_DIR / "data" / "tableau_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    for f in (BASE_DIR / "data" / "processed").glob("*.csv"):
        shutil.copy(f, export_dir / f.name)
"""
    if "shutil.copy" not in code:
        code = code.replace("print(\"\\n\" + \"=\"*60)", sync_code + "\n    print(\"\\n\" + \"=\"*60)")
        pipe_path.write_text(code)
        print("✅ Added auto-sync to run_pipeline.py for Tableau exports")
'

# 4. Wipe dirty fact table states in Oracle to allow a clean initial commit
python3 -c '
import os, oracledb
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
        for tbl in ["fact_attribution_events", "fact_touchpoints", "fact_daily_spend", "fact_leads"]:
            try:
                cur.execute(f"DELETE FROM {tbl}")
            except Exception:
                pass
    conn.commit()
    conn.close()
    print("✅ Reset Oracle fact tables for fresh automated run.")
except Exception as e:
    print(f"⚠️ Note during reset: {e}")
'

echo "============================================================"
echo "🚀 Executing End-to-End Analytics Pipeline..."
echo "============================================================"

# Run pipeline
python run_pipeline.py

echo "============================================================"
echo "📊 Current files in data/tableau_exports/:"
ls -lh data/tableau_exports/
echo "============================================================"
