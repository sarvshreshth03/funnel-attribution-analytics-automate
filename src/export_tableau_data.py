"""
export_tableau_data.py
Dumps warehouse views from Oracle to data/tableau_exports/*.csv 
for zero-friction Tableau Desktop / Tableau Public ingestion.
"""

import os
import argparse
import oracledb
import pandas as pd

VIEWS_TO_EXPORT = [
    ("v_daily_channel_kpis", "v_daily_channel_kpis.csv"),
    ("v_funnel_stage_conversion", "v_funnel_stage_conversion.csv"),
    ("v_cohort_lead_to_enrollment", "v_cohort_lead_to_enrollment.csv"),
    ("v_channel_attribution_comparison", "v_channel_attribution_comparison.csv")
]

def export_views(dsn: str, user: str, pwd: str):
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/tableau_exports"))
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Connecting to Oracle ({dsn}) as {user}...")
    conn = oracledb.connect(user=user, password=pwd, dsn=dsn)

    for view_name, csv_filename in VIEWS_TO_EXPORT:
        print(f"Exporting {view_name}...")
        sql = f"SELECT * FROM {view_name}"
        df = pd.read_sql(sql, conn)
        df.columns = [c.lower() for c in df.columns]
        
        target_path = os.path.join(output_dir, csv_filename)
        df.to_csv(target_path, index=False)
        print(f" -> Saved {len(df):,} rows to {target_path}")

    conn.close()
    print("\nAll views exported successfully to data/tableau_exports/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export SQL Views to CSV for Tableau")
    parser.add_argument("--dsn", default="localhost:1521/FREEPDB1")
    parser.add_argument("--user", default="funnel_prj")
    args = parser.parse_args()

    pwd = os.environ.get("FUNNEL_DB_PASSWORD", "Funnel_Pass1")
    export_views(args.dsn, args.user, pwd)