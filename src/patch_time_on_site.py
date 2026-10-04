from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

def patch():
    raw_dir = ROOT / "data" / "raw"
    csv_path = raw_dir / "leads.csv"
    if not csv_path.exists():
        csv_path = raw_dir / "Leads.csv"

    print(f"Reading {csv_path}...")
    if not csv_path.exists():
        raise FileNotFoundError(f"Neither leads.csv nor Leads.csv found in {raw_dir}")

    df = pd.read_csv(csv_path)

    # Standardize column naming for Total Time Spent on Website if needed
    col_candidates = [
        "Total Time Spent on Website",
        "total_time_spent_on_website",
        "time_on_site_sec",
    ]
    matched = None
    for col in col_candidates:
        if col in df.columns:
            matched = col
            break

    if matched:
        df["time_on_site_sec"] = df[matched].fillna(0)

    out_dir = ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "leads_cleaned.csv"
    
    # Save patched output
    df.to_csv(out_path, index=False)
    print(f"✓ Patched features written to {out_path}")

if __name__ == "__main__":
    patch()
