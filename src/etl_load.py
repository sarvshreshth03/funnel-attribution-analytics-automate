#!/usr/bin/env python3
"""Day 2 ETL: load the Day-1 synthetic CSVs + raw Kaggle leads into the FUNNEL_PRJ
Oracle schema, cleaning the defects injected by generate_synthetic.py on the way.

Order matters (dimensions before facts, parents before children):
  dim_channel -> dim_course -> dim_campaign -> fact_leads -> fact_touchpoints -> fact_spend

Usage:
  export FUNNEL_DB_PASSWORD='Funnel_Pass1'      # don't hardcode it in the script
  python src/etl_load.py --dsn localhost:1521/FREEPDB1 --user funnel_prj
"""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

import numpy as np
import oracledb
import pandas as pd

from clean import clean_campaign_id, clean_specialization, dedupe_exact, map_channel, normalize_source

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
RAW = ROOT / "data" / "raw"


def date_key(series: pd.Series) -> pd.Series:
    d = pd.to_datetime(series, errors="coerce")
    return d.dt.strftime("%Y%m%d").astype("Int64")


def load_dim_channel(cur, chan_map: pd.DataFrame) -> pd.DataFrame:
    dim = chan_map.drop_duplicates("channel_name")[["channel_name", "channel_group", "is_paid"]]
    cur.executemany(
        """MERGE INTO dim_channel d USING (SELECT :1 channel_name, :2 channel_group, :3 is_paid FROM dual) s
           ON (d.channel_name = s.channel_name)
           WHEN NOT MATCHED THEN INSERT (channel_name, channel_group, is_paid)
                VALUES (s.channel_name, s.channel_group, s.is_paid)""",
        dim.values.tolist(),
    )
    cur.connection.commit()
    cur.execute("SELECT channel_key, channel_name FROM dim_channel")
    return pd.DataFrame(cur.fetchall(), columns=["channel_key", "channel_name"])


def load_dim_course(cur, specializations: pd.Series) -> pd.DataFrame:
    vals = [[s] for s in sorted(specializations.unique())]
    cur.executemany(
        """MERGE INTO dim_course d USING (SELECT :1 specialization FROM dual) s
           ON (d.specialization = s.specialization)
           WHEN NOT MATCHED THEN INSERT (specialization) VALUES (s.specialization)""",
        vals,
    )
    cur.connection.commit()
    cur.execute("SELECT course_key, specialization FROM dim_course")
    return pd.DataFrame(cur.fetchall(), columns=["course_key", "specialization"])


def load_dim_campaign(cur, master: pd.DataFrame, dim_channel: pd.DataFrame) -> pd.DataFrame:
    m = master.merge(dim_channel, left_on="platform", right_on="channel_name", how="left")
    if m["channel_key"].isna().any():
        missing = m.loc[m["channel_key"].isna(), "platform"].unique()
        raise SystemExit(f"campaign_master.csv has platforms not in dim_channel: {missing}")
    rows = m[["campaign_id", "campaign_name", "channel_key", "objective", "start_date", "end_date"]].values.tolist()
    cur.executemany(
        """MERGE INTO dim_campaign d USING (SELECT :1 campaign_id FROM dual) s
           ON (d.campaign_id = s.campaign_id)
           WHEN NOT MATCHED THEN INSERT (campaign_id, campaign_name, channel_key, objective, start_date, end_date)
                VALUES (s.campaign_id, :2, :3, :4, TO_DATE(:5,'YYYY-MM-DD'), TO_DATE(:6,'YYYY-MM-DD'))""",
        rows,
    )
    other_rows = dim_channel.loc[dim_channel["channel_name"] == "Other", "channel_key"]
    if other_rows.empty:
        raise SystemExit("dim_channel has no 'Other' row -- check config/channel_mapping.csv")
    other_channel_key = int(other_rows.iloc[0])
    cur.execute(
        """MERGE INTO dim_campaign d USING (SELECT '(unmapped)' campaign_id FROM dual) s
           ON (d.campaign_id = s.campaign_id)
           WHEN NOT MATCHED THEN INSERT (campaign_id, campaign_name, channel_key, objective)
                VALUES ('(unmapped)', 'Unmapped / missing campaign', :1, NULL)""",
        [other_channel_key],
    )
    cur.execute(
        """MERGE INTO dim_campaign d USING (SELECT '(none)' campaign_id FROM dual) s
           ON (d.campaign_id = s.campaign_id)
           WHEN NOT MATCHED THEN INSERT (campaign_id, campaign_name, channel_key, objective)
                VALUES ('(none)', 'Not a paid touch', :1, NULL)""",
        [other_channel_key],
    )
    cur.connection.commit()
    cur.execute("SELECT campaign_key, campaign_id FROM dim_campaign")
    return pd.DataFrame(cur.fetchall(), columns=["campaign_key", "campaign_id"])


def build_clean_crm(crm_raw: pd.DataFrame, leads_raw: pd.DataFrame, chan_map: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    log: dict = {}
    crm, dup_n = dedupe_exact(crm_raw)
    log["exact_duplicate_rows_removed"] = dup_n

    src_norm = normalize_source(crm["utm_source"])
    chan = map_channel(src_norm, chan_map)
    crm = crm.assign(_channel_name=chan["channel_name"].values, _is_paid=chan["is_paid"].astype(int).values)

    before_blank = (crm["utm_campaign"].isna() | (crm["utm_campaign"].astype(str).str.strip() == "")).sum()
    crm["utm_campaign_clean"] = clean_campaign_id(crm["utm_campaign"])
    # a paid lead with no usable campaign id is a real DQ issue worth counting explicitly
    log["paid_leads_with_missing_campaign"] = int(
        ((crm["_is_paid"] == 1) & (crm["utm_campaign_clean"] == "(unmapped)")).sum()
    )
    log["utm_campaign_blank_filled"] = int(before_blank)

    # leads_raw arrives with "Prospect ID" already renamed to "prospect_id" by main()
    behav_cols = {
        "prospect_id": "prospect_id", "Lead Origin": "lead_origin",
        "What is your current occupation": "current_occupation", "City": "city",
        "TotalVisits": "total_visits", "Page Views Per Visit": "page_views_per_visit",
        "Last Activity": "last_activity", "Specialization": "specialization",
    }
    present = {k: v for k, v in behav_cols.items() if k in leads_raw.columns}
    behav = leads_raw[list(present)].rename(columns=present)
    if "specialization" in behav.columns:
        behav["specialization"] = clean_specialization(behav["specialization"])
    crm = crm.merge(behav, on="prospect_id", how="left")
    for col in ["lead_origin", "current_occupation", "city", "total_visits", "page_views_per_visit", "last_activity", "specialization"]:
        if col not in crm.columns:
            crm[col] = np.nan
    crm["specialization"] = crm["specialization"].fillna("Unspecified")
    return crm, log


def load_fact_leads(cur, crm: pd.DataFrame, dim_channel, dim_campaign, dim_course) -> pd.DataFrame:
    df = crm.merge(dim_channel, left_on="_channel_name", right_on="channel_name", how="left")
    df = df.merge(dim_campaign, left_on="utm_campaign_clean", right_on="campaign_id", how="left")
    df = df.merge(dim_course, on="specialization", how="left")
    df["created_date_key"] = date_key(df["lead_created_date"])
    df["enrollment_date_key"] = date_key(df["enrollment_date"])

    # converted_flag isn't a column in crm_lead_timeline.csv by design (Day 1 kept it out of the
    # "raw extract") -> derive it from max_stage_reached == 5, the same rule the DDL check enforces.
    df["converted_flag"] = (df["max_stage_reached"] == 5).astype(int)

    def row2(r):
        return [
            r.prospect_id, int(r.lead_number) if pd.notna(r.lead_number) else None,
            int(r.created_date_key), int(r.channel_key),
            int(r.campaign_key) if pd.notna(r.campaign_key) else None,
            int(r.course_key) if pd.notna(r.course_key) else None,
            r.lead_origin if pd.notna(r.lead_origin) else None,
            r.current_occupation if pd.notna(r.current_occupation) else None,
            r.city if pd.notna(r.city) else None,
            int(r.total_visits) if pd.notna(r.total_visits) else None,
            float(r.page_views_per_visit) if pd.notna(r.page_views_per_visit) else None,
            r.last_activity if pd.notna(r.last_activity) else None,
            int(r.max_stage_reached), int(r.converted_flag),
            int(r.enrollment_date_key) if pd.notna(r.enrollment_date_key) else None,
            float(r.commission_inr) if pd.notna(r.commission_inr) else None,
        ]

    rows = [row2(r) for r in df.itertuples(index=False)]
    cur.executemany(
        """INSERT INTO fact_leads
           (prospect_id, lead_number, created_date_key, source_channel_key, campaign_key, course_key,
            lead_origin, current_occupation, city, total_visits, page_views_per_visit, last_activity,
            max_stage_key, converted_flag, enrollment_date_key, commission_inr)
           VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13,:14,:15,:16)""",
        rows,
    )
    cur.connection.commit()
    cur.execute("SELECT lead_key, prospect_id FROM fact_leads")
    return pd.DataFrame(cur.fetchall(), columns=["lead_key", "prospect_id"])


def load_fact_touchpoints(cur, tp_raw: pd.DataFrame, chan_map, dim_channel, dim_campaign, fact_leads) -> dict:
    tp, dup_n = dedupe_exact(tp_raw, subset=["prospect_id", "touch_seq"])
    src_norm = normalize_source(tp["utm_source"])
    chan = map_channel(src_norm, chan_map)
    tp = tp.assign(_channel_name=chan["channel_name"].values)
    tp["utm_campaign_clean"] = clean_campaign_id(tp["utm_campaign"])
    tp["touch_date_key"] = date_key(tp["touch_date"])

    df = tp.merge(fact_leads, on="prospect_id", how="inner")  # inner: orphan touches would be a DQ bug
    orphans = len(tp) - len(df)
    df = df.merge(dim_channel, left_on="_channel_name", right_on="channel_name", how="left")
    df = df.merge(dim_campaign, left_on="utm_campaign_clean", right_on="campaign_id", how="left")

    rows = [
        [int(r.lead_key), int(r.touch_seq), int(r.touch_date_key), int(r.channel_key),
         int(r.campaign_key) if pd.notna(r.campaign_key) else None]
        for r in df.itertuples(index=False)
    ]
    cur.executemany(
        """INSERT INTO fact_touchpoints (lead_key, touch_seq, touch_date_key, channel_key, campaign_key)
           VALUES (:1,:2,:3,:4,:5)""",
        rows,
    )
    cur.connection.commit()
    return {"touchpoints_duplicate_rows_removed": dup_n, "touchpoints_orphaned_prospect_id": orphans}


def load_fact_spend(cur, spend: pd.DataFrame, dim_campaign) -> None:
    df = spend.merge(dim_campaign, on="campaign_id", how="inner")
    df["date_key"] = date_key(df["date"])
    rows = [
        [int(r.date_key), int(r.campaign_key), int(r.impressions), int(r.clicks), float(r.cost_inr)]
        for r in df.itertuples(index=False)
    ]
    cur.executemany(
        "INSERT INTO fact_spend (date_key, campaign_key, impressions, clicks, spend_inr) VALUES (:1,:2,:3,:4,:5)",
        rows,
    )
    cur.connection.commit()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", default="localhost:1521/FREEPDB1")
    ap.add_argument("--user", default="funnel_prj")
    ap.add_argument("--leads", type=Path, default=RAW / "Leads.csv")
    args = ap.parse_args()

    password = os.environ.get("FUNNEL_DB_PASSWORD") or getpass.getpass(f"Password for {args.user}: ")

    chan_map = pd.read_csv(ROOT / "config" / "channel_mapping.csv")
    master = pd.read_csv(SYN / "campaign_master.csv")
    crm_raw = pd.read_csv(SYN / "crm_lead_timeline.csv")
    tp_raw = pd.read_csv(SYN / "touchpoints.csv")
    spend = pd.read_csv(SYN / "ad_spend_daily.csv")
    leads_raw = pd.read_csv(args.leads)
    leads_raw.columns = [c.strip() for c in leads_raw.columns]
    leads_raw = leads_raw.rename(columns={"Prospect ID": "prospect_id"})

    crm, dq_log = build_clean_crm(crm_raw, leads_raw, chan_map)
    crm = crm.drop_duplicates(subset=["prospect_id"], keep="first")

    with oracledb.connect(user=args.user, password=password, dsn=args.dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur_clean:
            for tbl in ["fact_attribution_events", "fact_touchpoints", "fact_spend", "fact_daily_spend", "fact_leads"]:
                try:
                    cur_clean.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
            print("Cleared existing fact records.")
        cur = conn.cursor()
        print("Loading dim_channel ...")
        dim_channel = load_dim_channel(cur, chan_map)
        print("Loading dim_course ...")
        dim_course = load_dim_course(cur, crm["specialization"])
        print("Loading dim_campaign ...")
        dim_campaign = load_dim_campaign(cur, master, dim_channel)
        print("Loading fact_leads ...")
        fact_leads = load_fact_leads(cur, crm, dim_channel, dim_campaign, dim_course)
        print("Loading fact_touchpoints ...")
        tp_log = load_fact_touchpoints(cur, tp_raw, chan_map, dim_channel, dim_campaign, fact_leads)
        print("Loading fact_spend ...")
        load_fact_spend(cur, spend, dim_campaign)
        dq_log.update(tp_log)

    print("\n=== Data-quality log (compare against data/synthetic/_injection_log.json) ===")
    for k, v in dq_log.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
