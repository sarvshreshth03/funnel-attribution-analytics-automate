import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(
    page_title="Marketing Attribution & Lead Scoring",
    page_icon="🎯",
    layout="wide"
)

ROOT = Path(__file__).resolve().parent.parent
EXP_DIR = ROOT / "data" / "tableau_exports"

def load(filename):
    p = EXP_DIR / filename
    if p.exists() and p.stat().st_size > 0:
        return pd.read_csv(p)
    return pd.DataFrame()

st.title("🎯 Marketing Funnel Attribution & Lead Scoring Analytics")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Attribution Comparison", 
    "📈 Lead Scoring & Lift", 
    "📅 Daily Channel KPIs", 
    "🔻 Funnel Stage Conversion"
])

# --- TAB 1: Attribution Comparison ---
with tab1:
    st.subheader("Multi-Touch Attribution Model Performance")
    df_attr = load("v_channel_attribution_comparison.csv")
    if not df_attr.empty:
        st.dataframe(df_attr, use_container_width=True)
        
        # Plot Revenue Comparison
        st.subheader("Attributed Revenue by Channel (First-Touch vs Last-Touch)")
        ch_col = [c for c in df_attr.columns if "channel_name" in c.lower()]
        rev_cols = [c for c in df_attr.columns if "revenue" in c.lower()]
        if ch_col and rev_cols:
            chart_df = df_attr.set_index(ch_col[0])[rev_cols]
            st.bar_chart(chart_df)
    else:
        st.warning("Attribution dataset not found.")

# --- TAB 2: Lead Scoring & Lift ---
with tab2:
    st.subheader("Gradient Boosting Lead Scoring Decile Lift")
    col1, col2 = st.columns([1.2, 1])
    
    df_dec = load("lead_score_deciles.csv")
    with col1:
        if not df_dec.empty:
            st.dataframe(df_dec, use_container_width=True)
            st.subheader("Conversion Rate (%) by Decile")
            st.line_chart(df_dec.set_index("decile")["conversion_rate_pct"])
        else:
            st.warning("Decile dataset not found.")

    with col2:
        df_fi = load("top_feature_importances.csv")
        if not df_fi.empty:
            st.subheader("Top Predictive Feature Drivers")
            st.bar_chart(df_fi.set_index("feature")["importance"])
        else:
            st.warning("Feature importance dataset not found.")

# --- TAB 3: Daily Channel KPIs ---
with tab3:
    st.subheader("Aggregated Performance Metrics")
    df_kpi = load("v_daily_channel_kpis.csv")
    if not df_kpi.empty:
        c1, c2, c3 = st.columns(3)
        spend = next((c for c in df_kpi.columns if "spend" in c.lower()), None)
        imp = next((c for c in df_kpi.columns if "impression" in c.lower()), None)
        clk = next((c for c in df_kpi.columns if "click" in c.lower()), None)
        
        if spend:
            c1.metric("Total Spend", f"₹{df_kpi[spend].sum():,.0f}")
        if imp:
            c2.metric("Total Impressions", f"{df_kpi[imp].sum():,.0f}")
        if clk:
            c3.metric("Total Clicks", f"{df_kpi[clk].sum():,.0f}")
            
        st.dataframe(df_kpi, use_container_width=True)
    else:
        st.warning("Daily KPIs not found.")

# --- TAB 4: Funnel Stage Conversion ---
with tab4:
    st.subheader("Funnel Stage Drop-Off Analysis")
    df_funnel = load("v_funnel_stage_conversion.csv")
    if not df_funnel.empty:
        st.dataframe(df_funnel, use_container_width=True)
    else:
        st.warning("Funnel stage conversion data not found.")
