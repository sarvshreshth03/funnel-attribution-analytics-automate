"""
run_pipeline.py - Master Pipeline Orchestrator
Executes end-to-end data processing, ETL, modeling, and dashboard export.
"""

import os
import sys
import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from config/database.env
env_file = BASE_DIR / "config" / "database.env"
if env_file.exists():
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

def run_step(step_name, command):
    print(f"\n{'='*60}\n▶ Running: {step_name}\n{'='*60}")
    start = time.time()
    result = subprocess.run(command, shell=True, cwd=BASE_DIR, env=os.environ)
    if result.returncode != 0:
        print(f"❌ ERROR: {step_name} failed with return code {result.returncode}")
        sys.exit(result.returncode)
    print(f"✓ Completed in {time.time() - start:.2f}s")

def main():
    print("🚀 Initiating Full End-to-End Analytics Pipeline...")

    # 1. Clean & validate raw leads
    run_step("1. Data Cleaning & Validation", "python src/clean.py")

    # 2. Synthesize multi-touch touchpoints and daily spend
    run_step("2. Touchpoint & Spend Generation", "python src/generate_synthetic.py")

    # 3. Load facts and dimensions into Oracle
    run_step("3. Oracle DB ETL Load", "python src/etl_load.py --dsn localhost:1521/FREEPDB1 --user funnel_prj")

    # 4. Feature engineering adjustments
    run_step("4. Feature Patching", "python src/patch_time_on_site.py")

    # 5. Train predictive lead scoring model
    run_step("5. Train Lead Scoring Model", "python src/lead_scoring.py")

    # 6. Refresh CSV extracts for Tableau
    run_step("6. Export Tableau Data Views", "python src/export_tableau_data.py")

    
    # Sync all generated exports into data/tableau_exports/
    export_dir = BASE_DIR / "data" / "tableau_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    for f in (BASE_DIR / "data" / "processed").glob("*.csv"):
        shutil.copy(f, export_dir / f.name)

    print("\n" + "="*60)
    print(" All transformations, models, and CSV extracts refreshed!")
    print(" Open dashboards/funnel_attribution_analytics.twb to view updated metrics.")
    print("="*60)

if __name__ == "__main__":
    main()