#!/usr/bin/env python3
"""Generate the synthetic source-system extracts for the funnel & attribution project.

Inputs
  data/raw/Leads.csv          Kaggle "Lead Scoring" dataset (real lead behaviour + Converted flag)
  config/channel_mapping.csv  raw utm_source -> channel / group / paid flag
  config/campaigns.csv        campaign master with cost & quality assumptions

Outputs (data/synthetic/)
  crm_lead_timeline.csv   one row per lead: created date, last-touch UTM, stage reached, enrollment
  touchpoints.csv         multi-touch journeys per lead (last touch == the CRM lead-source record)
  ad_spend_daily.csv      daily impressions / clicks / cost per paid campaign
  campaign_master.csv     campaign dimension source
  _injection_log.json     answer key: how many data-quality defects were injected (Day 2 tests)

What is REAL vs SIMULATED
  Real (Kaggle): lead behaviour, specialization, Lead Source (treated as the last touch),
                 and the Converted flag (treated as "enrolled").
  Simulated:     lead created dates, campaigns, earlier touchpoints, ad spend, funnel stage
                 reached, enrollment date, commission. Everything is seeded and reproducible.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# --- journey shape ---------------------------------------------------------------
# P(number of assist touches 0..3 before the lead-creating touch). Converters have longer journeys.
ASSIST_P_CONVERTED = [0.20, 0.30, 0.30, 0.20]
ASSIST_P_NOT_CONVERTED = [0.40, 0.35, 0.18, 0.07]
# Channels that tend to start / assist journeys (Meta & YouTube introduce, Direct/Chat close).
ASSIST_CHANNEL_WEIGHTS = {
    "Meta Ads": 0.22, "Organic Search": 0.20, "Google Ads": 0.16, "YouTube Ads": 0.14,
    "Direct": 0.10, "Social Organic": 0.06, "Email": 0.05, "Referral": 0.04, "Microsoft Ads": 0.03,
}
# --- funnel stages -----------------------------------------------------------------
# 1 Lead Captured, 2 Contacted, 3 Qualified, 4 Applied, 5 Enrolled (only converted leads)
STAGE_BASE_NOT_CONVERTED = np.array([0.30, 0.35, 0.25, 0.10])
# --- commission per enrollment (INR) --------------------------------------------------
COMMISSION_BY_SPECIALIZATION = {
    "finance management": 16000, "human resource management": 13000, "marketing management": 14000,
    "operations management": 13000, "business administration": 15000, "it projects management": 17000,
    "supply chain management": 14000, "banking investment and insurance": 16000,
    "international business": 15000, "healthcare management": 18000, "e-commerce": 12000,
    "e-business": 12000,
}
DEFAULT_COMMISSION = 12000


def load_leads(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"Leads file not found: {path}\nDownload the Kaggle 'Lead Scoring' Leads.csv into data/raw/.")
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    need = ["Prospect ID", "Lead Number", "Lead Source", "Converted", "Specialization",
            "Total Time Spent on Website"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise SystemExit(f"Leads file is missing expected columns: {missing}")
    return df


def sample_created_dates(rng, start: pd.Timestamp, days: int, n: int) -> pd.DatetimeIndex:
    """Lead volume: upward trend, weekday > weekend, daily noise, one admissions-season promo spike."""
    idx = pd.date_range(start, periods=days, freq="D")
    t = np.arange(days) / max(days - 1, 1)
    dow = idx.dayofweek.to_numpy()
    dow_factor = np.where(dow < 5, 1.0, np.where(dow == 5, 0.8, 0.65))
    w = (1 + 0.6 * t) * dow_factor * rng.lognormal(0, 0.15, days)
    w = np.where((t >= 0.50) & (t < 0.54), w * 1.6, w)
    return idx[rng.choice(days, size=n, p=w / w.sum())]


def make_campaign_picker(camps: pd.DataFrame, rng):
    by_channel: dict[str, list[dict]] = {}
    for c in camps.to_dict("records"):
        by_channel.setdefault(c["platform"], []).append(c)

    def pick(channel: str, date: pd.Timestamp, converted: int):
        active = [c for c in by_channel.get(channel, []) if c["start_date"] <= date <= c["end_date"]]
        if not active:
            return None
        # High-quality campaigns are over-represented among converters -> real signal for Day 4/5.
        w = np.array([c["weight"] * (c["quality"] if converted else 1.0) for c in active])
        return active[rng.choice(len(active), p=w / w.sum())]

    return pick


def inject_utm_noise(series: pd.Series, rng, rate: float):
    """Case / whitespace defects in utm_source, to be fixed by the Day 2 cleaning step."""
    variants = [lambda x: x.upper(), lambda x: x.title() + " ", lambda x: " " + x, lambda x: x.capitalize()]
    s = series.copy()
    idx = np.flatnonzero(rng.random(len(s)) < rate)
    for j in idx:
        s.iat[j] = variants[rng.integers(len(variants))](s.iat[j])
    return s, int(len(idx))


def print_summary(crm: pd.DataFrame, tp: pd.DataFrame, spend: pd.DataFrame) -> None:
    """Sanity check on the CLEAN data: do the numbers look like a plausible lead-gen business?"""
    n_touch = tp.groupby("prospect_id")["touch_seq"].transform("max")
    tp = tp.assign(
        credit=1.0 / n_touch, is_first=(tp["touch_seq"] == 1), is_last=(tp["touch_seq"] == n_touch)
    ).merge(crm[["prospect_id", "_converted", "commission_inr"]], on="prospect_id")
    conv = tp[tp["_converted"] == 1]
    g = conv.groupby("_channel")
    out = pd.DataFrame({
        "first_touch_enr": g["is_first"].sum(),
        "last_touch_enr": g["is_last"].sum(),
        "linear_enr": g["credit"].sum().round(0),
        "linear_revenue": (conv["credit"] * conv["commission_inr"]).groupby(conv["_channel"]).sum().round(0),
    })
    out["spend"] = spend.groupby("platform")["cost_inr"].sum().round(0)
    paid = out.dropna(subset=["spend"]).copy()
    paid["cost_per_enr_last"] = (paid["spend"] / paid["last_touch_enr"].replace(0, np.nan)).round(0)
    paid["cost_per_enr_linear"] = (paid["spend"] / paid["linear_enr"].replace(0, np.nan)).round(0)
    paid["roas_linear"] = (paid["linear_revenue"] / paid["spend"]).round(2)
    pd.set_option("display.width", 200)
    print("\n=== Sanity summary (clean data, paid channels) ===")
    print(paid.to_string())
    total = spend["cost_inr"].sum()
    print(f"\nTotal spend INR {total:,.0f} | leads {len(crm):,} | enrollments {int(crm['_converted'].sum()):,} "
          f"| touchpoints {len(tp):,} | avg touches/lead {len(tp) / len(crm):.2f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leads", type=Path, default=ROOT / "data" / "raw" / "Leads.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "synthetic")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2026-01-01", help="first lead-created date")
    ap.add_argument("--days", type=int, default=180, help="length of the lead-creation window")
    ap.add_argument("--clean", action="store_true", help="do not inject data-quality defects")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    start = pd.Timestamp(args.start)
    end = start + pd.Timedelta(days=args.days - 1)

    chan_map = pd.read_csv(ROOT / "config" / "channel_mapping.csv")
    map_dict = {r.source_raw: r for r in chan_map.itertuples()}
    first_source = chan_map.drop_duplicates("channel_name").set_index("channel_name")["source_raw"].to_dict()
    paid_channels = set(chan_map.loc[chan_map["is_paid"] == 1, "channel_name"])

    camps = pd.read_csv(ROOT / "config" / "campaigns.csv")
    camps["start_date"] = camps["start_offset_days"].apply(lambda x: start + pd.Timedelta(days=int(x)))
    camps["end_date"] = camps["end_offset_days"].apply(
        lambda x: end if pd.isna(x) else start + pd.Timedelta(days=int(x)))
    pick_campaign = make_campaign_picker(camps, rng)

    assist_channels = list(ASSIST_CHANNEL_WEIGHTS)
    assist_p = np.array(list(ASSIST_CHANNEL_WEIGHTS.values()))
    assist_p = assist_p / assist_p.sum()

    leads = load_leads(args.leads)
    n = len(leads)
    created = sample_created_dates(rng, start, args.days, n)
    t_sec = leads["Total Time Spent on Website"].fillna(0).astype(float).to_numpy()
    time_z = (t_sec - t_sec.mean()) / (t_sec.std() or 1.0)
    pids = leads["Prospect ID"].astype(str).to_numpy()
    lnums = leads["Lead Number"].to_numpy()
    sources = leads["Lead Source"].to_numpy()
    converted = leads["Converted"].astype(int).to_numpy()
    specs = leads["Specialization"].to_numpy()

    crm_rows, tp_rows = [], []
    for i in range(n):
        conv, c_date = int(converted[i]), created[i]
        src = str(sources[i]).strip().lower() if pd.notna(sources[i]) else "unknown"
        m = map_dict.get(src, map_dict["other"])
        camp = pick_campaign(m.channel_name, c_date, conv) if m.is_paid == 1 else None

        # journey: the Kaggle lead source is the LAST touch; earlier assist touches are simulated
        touches = [(c_date, src, m.utm_medium, m.channel_name, camp)]
        d = c_date
        for _ in range(rng.choice(4, p=ASSIST_P_CONVERTED if conv else ASSIST_P_NOT_CONVERTED)):
            d = d - pd.Timedelta(days=1 + int(rng.exponential(4)))
            if d < start:            # lookback truncated at the start of the data window
                break
            ch = str(rng.choice(assist_channels, p=assist_p))
            a_camp = None
            if ch in paid_channels:
                a_camp = pick_campaign(ch, d, conv)
                if a_camp is None:   # no campaign live yet on that date
                    ch = "Organic Search"
            a_src = first_source.get(ch, src if src else 'Direct Traffic')
            touches.append((d, a_src, map_dict[a_src].utm_medium, ch, a_camp))
        touches.sort(key=lambda t: t[0])
        for seq, (td, s, med, ch, cp) in enumerate(touches, start=1):
            tp_rows.append({
                "prospect_id": pids[i], "touch_seq": seq, "touch_date": td, "utm_source": s,
                "utm_medium": med, "utm_campaign": cp["campaign_id"] if cp else "(none)",
                "campaign_id": cp["campaign_id"] if cp else None, "_channel": ch,
            })

        # funnel outcome
        if conv:
            stage = 5
            lag = int(np.clip(round(rng.gamma(3.0, 6.0)) + 1, 1, 60))
            enroll = c_date + pd.Timedelta(days=lag)
            base = COMMISSION_BY_SPECIALIZATION.get(str(specs[i]).strip().lower(), DEFAULT_COMMISSION)
            commission = round(base * rng.lognormal(0, 0.15) / 100) * 100
        else:
            z = float(np.clip(time_z[i], -2, 2))
            w = STAGE_BASE_NOT_CONVERTED * np.exp(0.35 * z * (np.arange(1, 5) - 2.5))
            stage = 1 + int(rng.choice(4, p=w / w.sum()))
            enroll, commission = pd.NaT, np.nan

        crm_rows.append({
            "prospect_id": pids[i], "lead_number": lnums[i], "lead_created_date": c_date,
            "utm_source": src, "utm_medium": m.utm_medium,
            "utm_campaign": camp["campaign_id"] if camp else "(none)",
            "max_stage_reached": stage, "enrollment_date": enroll, "commission_inr": commission,
            "_converted": conv, "_channel": m.channel_name,
        })

    crm, tp = pd.DataFrame(crm_rows), pd.DataFrame(tp_rows)

    # --- ad spend: every identified paid touch implies clicks; some clicks never become leads ---
    counts = tp[tp["campaign_id"].notna()].groupby(["campaign_id", "touch_date"]).size().to_dict()
    spend_rows = []
    for c in camps.itertuples():
        for d in pd.date_range(c.start_date, c.end_date):
            touches_today = counts.get((c.campaign_id, d), 0)
            clicks = int(round((touches_today + rng.poisson(0.6)) / c.ident_rate))
            cost = round(clicks * c.cpc_inr * rng.lognormal(0, 0.10), 2)
            impr = int(round(clicks / c.ctr * rng.lognormal(0, 0.05))) if clicks else 0
            spend_rows.append({"date": d, "campaign_id": c.campaign_id, "platform": c.platform,
                               "impressions": impr, "clicks": clicks, "cost_inr": cost})
    spend = pd.DataFrame(spend_rows)

    print_summary(crm, tp, spend)

    # --- inject controlled data-quality defects (answer key written to _injection_log.json) ---
    log = {"seed": args.seed, "defects_injected": not args.clean}
    crm_out = crm.drop(columns=["_converted", "_channel"])
    tp_out = tp.drop(columns=["campaign_id", "_channel"])
    if not args.clean:
        crm_out["utm_source"], log["crm_utm_source_case_whitespace"] = inject_utm_noise(crm_out["utm_source"], rng, 0.04)
        tp_out["utm_source"], log["touchpoints_utm_source_case_whitespace"] = inject_utm_noise(tp_out["utm_source"], rng, 0.03)
        paid_rows = np.flatnonzero((crm_out["utm_campaign"] != "(none)").to_numpy())
        miss = paid_rows[rng.random(len(paid_rows)) < 0.01]
        crm_out.loc[crm_out.index[miss], "utm_campaign"] = ""
        log["crm_missing_utm_campaign_on_paid_leads"] = int(len(miss))
        dup = crm_out.sample(frac=0.005, random_state=args.seed)
        crm_out = pd.concat([crm_out, dup]).sort_values("lead_created_date", kind="stable")
        log["crm_exact_duplicate_rows"] = int(len(dup))

    args.out.mkdir(parents=True, exist_ok=True)
    fmt = {"lead_created_date": "%Y-%m-%d", "enrollment_date": "%Y-%m-%d"}
    for col, f in fmt.items():
        crm_out[col] = pd.to_datetime(crm_out[col]).dt.strftime(f)
    tp_out["touch_date"] = tp_out["touch_date"].dt.strftime("%Y-%m-%d")
    spend["date"] = spend["date"].dt.strftime("%Y-%m-%d")
    master = camps[["campaign_id", "campaign_name", "platform", "objective", "start_date", "end_date"]].copy()
    master["start_date"] = master["start_date"].dt.strftime("%Y-%m-%d")
    master["end_date"] = master["end_date"].dt.strftime("%Y-%m-%d")

    crm_out.to_csv(args.out / "crm_lead_timeline.csv", index=False)
    tp_out.to_csv(args.out / "touchpoints.csv", index=False)
    spend.to_csv(args.out / "ad_spend_daily.csv", index=False)
    master.to_csv(args.out / "campaign_master.csv", index=False)
    (args.out / "_injection_log.json").write_text(json.dumps(log, indent=2))
    print(f"\nWrote 4 CSVs + injection log to {args.out}\n{json.dumps(log, indent=2)}")


if __name__ == "__main__":
    main()
