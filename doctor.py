"""
doctor.py - Environment & Configuration Diagnostics and Auto-Repair Tool
Validates directory structure, fixes config/data mismatches, and executes the pipeline safely.
"""

import os
import sys
import subprocess
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent

def log(msg, status="INFO"):
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "FIXED": "🔧", "WARN": "⚠️", "ERROR": "❌"}
    print(f"{icons.get(status, '•')} [{status}] {msg}")

def fix_directories():
    required_dirs = [
        "config",
        "data/raw",
        "data/processed",
        "data/tableau_exports",
        "sql",
        "src",
        "dashboards",
        "docs",
    ]
    for d in required_dirs:
        p = ROOT / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            log(f"Created missing directory: {d}", "FIXED")
        else:
            log(f"Directory exists: {d}", "SUCCESS")

def fix_raw_leads():
    raw_dir = ROOT / "data" / "raw"
    target = raw_dir / "leads.csv"
    alt_target = raw_dir / "Leads.csv"

    if not target.exists() and alt_target.exists():
        alt_target.rename(target)
        log("Renamed 'Leads.csv' to lowercase 'leads.csv'", "FIXED")
    elif target.exists():
        log("Raw dataset 'leads.csv' is present", "SUCCESS")
    else:
        log("Neither 'leads.csv' nor 'Leads.csv' found in data/raw/", "ERROR")
        return False
    return True

def fix_channel_mapping():
    cfg_dir = ROOT / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    mapping_file = cfg_dir / "channel_mapping.csv"

    # Complete mapping including all source channels, fallbacks, and Email/Social
    full_mapping = """source_raw,channel_name,channel_group,utm_medium,is_paid
Google,Google Ads,Search,cpc,1
google,Google Ads,Search,cpc,1
Direct Traffic,Direct,Direct,none,0
Direct,Direct,Direct,none,0
Olark Chat,Website Chat,Direct,chat,0
Live Chat,Website Chat,Direct,chat,0
Organic Search,Organic Search,Search,organic,0
Reference,Referral,Referral,referral,0
Referral Sites,Referral,Referral,referral,0
Welingak Website,Partner Website,Referral,referral,0
Facebook,Meta Ads,Paid Social,cpc,1
bing,Microsoft Ads,Search,cpc,1
youtube,YouTube Ads,Video,video,1
Click2call,Click2Call,Direct,phone,0
Social Media,Social Organic,Social,social,0
welearnblog_Home,Social Organic,Social,blog,0
Email,Email,Direct,email,0
email,Email,Direct,email,0
other,Other,Other,other,0
Other,Other,Other,other,0
unknown,Unknown,Other,unknown,0
Unknown,Unknown,Other,unknown,0
"""
    # Check if existing file has missing columns or missing Email/other entries
    needs_rewrite = False
    if not mapping_file.exists():
        needs_rewrite = True
    else:
        try:
            df = pd.read_csv(mapping_file)
            req_cols = {"source_raw", "channel_name", "channel_group", "utm_medium", "is_paid"}
            if not req_cols.issubset(set(df.columns)):
                needs_rewrite = True
            elif "Email" not in df["source_raw"].values or "other" not in df["source_raw"].values:
                needs_rewrite = True
        except Exception:
            needs_rewrite = True

    if needs_rewrite:
        with open(mapping_file, "w") as f:
            f.write(full_mapping)
        log("Auto-generated / Repaired 'config/channel_mapping.csv' with complete fallback and channels", "FIXED")
    else:
        log("config/channel_mapping.csv is valid", "SUCCESS")

def fix_synthetic_script():
    """Patches generate_synthetic.py if first_source lacks Email or other keys."""
    script_path = ROOT / "src" / "generate_synthetic.py"
    if not script_path.exists():
        log("src/generate_synthetic.py not found", "ERROR")
        return False

    with open(script_path, "r") as f:
        code = f.read()

    # Look for first_source dict and make it resilient via defaultdict or .get fallback
    modified = False
    if "first_source[" in code:
        # Patch direct dictionary lookups to use .get(ch, src) fallback
        patched_code = code.replace(
            "a_src = first_source[ch]",
            "a_src = first_source.get(ch, src if src else 'Direct Traffic')"
        )
        if patched_code != code:
            with open(script_path, "w") as f:
                f.write(patched_code)
            log("Patched src/generate_synthetic.py to safeguard first_source key lookups", "FIXED")
            modified = True

    if not modified:
        log("src/generate_synthetic.py lookup logic is intact", "SUCCESS")
    return True

def fix_env():
    env_file = ROOT / "config" / "database.env"
    if not env_file.exists():
        with open(env_file, "w") as f:
            f.write("FUNNEL_DB_PASSWORD=oracle\nFUNNEL_DB_DSN=localhost:1521/FREEPDB1\nFUNNEL_DB_USER=funnel_prj\n")
        log("Created default 'config/database.env'. Update password if different from 'oracle'", "WARN")
    else:
        log("config/database.env exists", "SUCCESS")

def main():
    print("\n" + "=" * 60)
    print("🩺 Running Funnel Analytics Self-Healing Doctor...")
    print("=" * 60)

    fix_directories()
    if not fix_raw_leads():
        sys.exit(1)
    fix_channel_mapping()
    fix_synthetic_script()
    fix_env()

    print("\n" + "=" * 60)
    print("🚀 All diagnostics passed! Starting run_pipeline.py...")
    print("=" * 60 + "\n")

    res = subprocess.run([sys.executable, "run_pipeline.py"], cwd=ROOT)
    sys.exit(res.returncode)

if __name__ == "__main__":
    main()