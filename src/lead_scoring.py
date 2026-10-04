from pathlib import Path
"""
Day 5: Predictive Lead Scoring Model
Trains Logistic Regression and Gradient Boosting models on fact_leads,
computes evaluation metrics, produces decile lift tables, and exports outputs.
"""

import os
import argparse
import oracledb
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    classification_report,
    roc_curve,
    precision_recall_curve
)

def fetch_data(dsn: str, user: str, pwd: str) -> pd.DataFrame:
    print(f"Connecting to Oracle at {dsn} as {user}...")
    conn = oracledb.connect(user=user, password=pwd, dsn=dsn)
    
    query = """
    SELECT 
        l.lead_key,
        l.lead_number,
        l.lead_origin,
        l.current_occupation,
        l.city,
        l.total_visits,
        l.time_on_site_sec,
        l.page_views_per_visit,
        l.last_activity,
        ch.channel_name,
        co.specialization,
        l.converted_flag
    FROM fact_leads l
    JOIN dim_channel ch ON l.source_channel_key = ch.channel_key
    JOIN dim_course co  ON l.course_key = co.course_key
    """
    
    print("Executing query to extract lead dataset...")
    df = pd.read_sql(query, conn)
    if df.empty or len(df) == 0:
        fb = Path(__file__).resolve().parent.parent / "data" / "processed" / "leads_cleaned.csv"
        print(f"Reading from cleaned CSV fallback: {fb}")
        df = pd.read_csv(fb)
        df.columns = [c.lower() for c in df.columns]
        if "converted" in df.columns:
            df["is_enrolled"] = df["converted"] if "converted" in df.columns else df.get("is_enrolled", 0)
        df["converted_flag"] = df["is_enrolled"] if "converted" in df.columns else df.get("is_enrolled", 0)

        # Map Kaggle raw columns to warehouse model feature names
        col_rename = {
            "totalvisits": "total_visits",
            "total visits": "total_visits",
            "page views per visit": "page_views_per_visit",
            "pageviewspervisit": "page_views_per_visit",
            "lead origin": "lead_origin",
            "leadorigin": "lead_origin",
            "current occupation": "current_occupation",
            "currentoccupation": "current_occupation",
            "last activity": "last_activity",
            "lastactivity": "last_activity",
            "lead source": "channel_name",
            "leadsource": "channel_name",
            "specialization": "specialization",
        }
        df = df.rename(columns=col_rename)

        # Fill default fallbacks for missing columns
        for col in ["total_visits", "page_views_per_visit", "time_on_site_sec"]:
            if col not in df.columns:
                df[col] = 0.0
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        for col in ["lead_origin", "current_occupation", "last_activity", "channel_name"]:
            if col not in df.columns:
                df[col] = "Unknown"
            else:
                df[col] = df[col].fillna("Unknown").astype(str)

        if "total time spent on website" in df.columns:
            df["time_on_site_sec"] = df["total time spent on website"].fillna(0)
        
    # Convert column names to lowercase for standard handling
    df.columns = [c.lower() for c in df.columns]
    conn.close()
    print(f"Retrieved {len(df):,} lead records.")
    return df

def build_decile_table(y_true: np.ndarray, y_prob: np.ndarray) -> pd.DataFrame:
    df_eval = pd.DataFrame({"actual": y_true, "prob": y_prob})
    # Cut into 10 deciles (Decile 1 = highest predicted score)
    df_eval["decile"] = pd.qcut(df_eval["prob"].rank(method="first", ascending=False), q=10, labels=range(1, 11))
    
    agg = df_eval.groupby("decile", observed=False).agg(
        leads=("actual", "count"),
        conversions=("actual", "sum"),
        min_score=("prob", "min"),
        max_score=("prob", "max")
    ).reset_index()
    
    total_leads = agg["leads"].sum()
    total_conversions = agg["conversions"].sum()
    overall_rate = total_conversions / total_leads
    
    agg["conversion_rate_pct"] = (agg["conversions"] / agg["leads"] * 100).round(2)
    agg["cum_leads"] = agg["leads"].cumsum()
    agg["cum_conversions"] = agg["conversions"].cumsum()
    agg["cum_capture_rate_pct"] = (agg["cum_conversions"] / total_conversions * 100).round(2)
    agg["decile_lift"] = (agg["conversion_rate_pct"] / (overall_rate * 100)).round(2)
    
    return agg

def main():
    parser = argparse.ArgumentParser(description="Lead Scoring Model Engine")
    parser.add_argument("--dsn", default="localhost:1521/FREEPDB1")
    parser.add_argument("--user", default="funnel_prj")
    args = parser.parse_args()

    pwd = os.environ.get("FUNNEL_DB_PASSWORD")
    if not pwd:
        raise ValueError("Environment variable FUNNEL_DB_PASSWORD is required.")

    df = fetch_data(args.dsn, args.user, pwd)

    # Define feature lists
    num_cols = ["total_visits", "time_on_site_sec", "page_views_per_visit"]
    cat_cols = ["lead_origin", "current_occupation", "city", "last_activity", "channel_name", "specialization"]
    target = "converted_flag"

    
    # Standardize time_on_site_sec
    for col in ["total_time_spent_on_website", "time_spent_on_website", "TOTAL_TIME_SPENT_ON_WEBSITE"]:
        if col in df.columns:
            df["time_on_site_sec"] = df[col].fillna(0)
            break
    if "time_on_site_sec" not in df.columns or df["time_on_site_sec"].isna().all():
        raw_csv = Path(__file__).resolve().parent.parent / "data" / "raw" / "leads.csv"
        if not raw_csv.exists():
            raw_csv = Path(__file__).resolve().parent.parent / "data" / "raw" / "Leads.csv"
        if raw_csv.exists():
            import pandas as pd
            raw_df = pd.read_csv(raw_csv)
            time_col = [c for c in raw_df.columns if "time" in c.lower()]
            if time_col:
                df["time_on_site_sec"] = raw_df[time_col[0]].fillna(0).values[:len(df)]

    X = df[num_cols + cat_cols]
    y = df[target].astype(int)

    # Train-test split (80/20, stratified)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    # Transformers
    num_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler())
    ])

    cat_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
        ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False))
    ])

    preprocessor = ColumnTransformer(transformers=[
        ("num", num_transformer, num_cols),
        ("cat", cat_transformer, cat_cols)
    ])

    # 1. Baseline: Logistic Regression
    print("\n--- Training Baseline: Logistic Regression ---")
    log_reg_pipe = Pipeline(steps=[
        ("prep", preprocessor),
        ("clf", LogisticRegression(max_iter=1000, random_state=42))
    ])
    log_reg_pipe.fit(X_train, y_train)
    y_pred_prob_lr = log_reg_pipe.predict_proba(X_test)[:, 1]
    y_pred_lr = (y_pred_prob_lr >= 0.5).astype(int)

    lr_roc_auc = roc_auc_score(y_test, y_pred_prob_lr)
    lr_pr_auc = average_precision_score(y_test, y_pred_prob_lr)
    print(f"Logistic Regression ROC-AUC: {lr_roc_auc:.4f} | PR-AUC: {lr_pr_auc:.4f}")

    # 2. Challenger: Gradient Boosting
    print("\n--- Training Challenger: Gradient Boosting ---")
    gb_pipe = Pipeline(steps=[
        ("prep", preprocessor),
        ("clf", GradientBoostingClassifier(n_estimators=150, learning_rate=0.08, max_depth=4, random_state=42))
    ])
    gb_pipe.fit(X_train, y_train)
    y_pred_prob_gb = gb_pipe.predict_proba(X_test)[:, 1]
    y_pred_gb = (y_pred_prob_gb >= 0.5).astype(int)

    gb_roc_auc = roc_auc_score(y_test, y_pred_prob_gb)
    gb_pr_auc = average_precision_score(y_test, y_pred_prob_gb)
    print(f"Gradient Boosting ROC-AUC:   {gb_roc_auc:.4f} | PR-AUC: {gb_pr_auc:.4f}")

    print("\n--- Classification Report (Gradient Boosting) ---")
    print(classification_report(y_test, y_pred_gb, digits=4))

    # Decile Lift Table (Gradient Boosting)
    print("\n--- Decile Lift Analysis (Test Set - Gradient Boosting) ---")
    decile_df = build_decile_table(y_test.values, y_pred_prob_gb)
    print(decile_df.to_string(index=False))

    # Top Feature Importances (Gradient Boosting)
    ohe_cols = gb_pipe.named_steps["prep"].named_transformers_["cat"].named_steps["ohe"].get_feature_names_out(cat_cols)
    feature_names = num_cols + list(ohe_cols)
    importances = gb_pipe.named_steps["clf"].feature_importances_
    
    try:
        # Dynamically fetch output feature names from the fitted preprocessor
        if hasattr(preprocessor, "get_feature_names_out"):
            fitted_names = preprocessor.get_feature_names_out()
        else:
            fitted_names = feature_names[:len(importances)]
    except Exception:
        fitted_names = [f"feat_{i}" for i in range(len(importances))]
    
    if len(fitted_names) != len(importances):
        fitted_names = fitted_names[:len(importances)]

    fi_df = pd.DataFrame({"feature": fitted_names, "importance": importances})

    fi_df = fi_df.sort_values(by="importance", ascending=False).head(10)
    print("\n--- Top 10 Feature Importances ---")
    print(fi_df.to_string(index=False))

    # Save output artifacts for Day 6 Dashboard
    os.makedirs("../data/processed", exist_ok=True)
    decile_df.to_csv("../data/processed/lead_score_deciles.csv", index=False)
    fi_df.to_csv("../data/processed/top_feature_importances.csv", index=False)
    
    # Score the entire fact_leads table to store lead scores for dashboarding
    print("\nScoring full dataset for BI reporting...")
    full_probs = gb_pipe.predict_proba(X)[:, 1]
    # Ensure lead identification columns exist
    if "lead_number" not in df.columns:
        df["lead_number"] = df.get("Lead Number", df.get("lead number", df.index + 1))
    if "lead_key" not in df.columns:
        df["lead_key"] = df.get("Prospect ID", df.get("prospect_id", df.index + 1))

    df_scored = df[["lead_key", "lead_number", "converted_flag"]].copy()
    df_scored["lead_score"] = (full_probs * 100).round(2)
    df_scored["lead_score_decile"] = pd.qcut(df_scored["lead_score"].rank(method="first", ascending=False), q=10, labels=range(1, 11))
    df_scored.to_csv("../data/processed/fact_leads_scored.csv", index=False)
    print("Saved scored leads to data/processed/fact_leads_scored.csv")

if __name__ == "__main__":
    main()