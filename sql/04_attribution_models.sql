-- =====================================================================
-- Day 4: Multi-Touch Attribution Models
-- Schema: FUNNEL_PRJ
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. VIEW: v_touchpoint_weights
-- Computes the credit weight of each touchpoint under 4 models.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_touchpoint_weights AS
WITH journey_meta AS (
    SELECT 
        tp.touchpoint_key,
        tp.lead_key,
        tp.touch_seq,
        tp.touch_date_key,
        tp.channel_key,
        tp.campaign_key,
        COUNT(*) OVER (PARTITION BY tp.lead_key) AS total_touches,
        MIN(tp.touch_seq) OVER (PARTITION BY tp.lead_key) AS first_seq,
        MAX(tp.touch_seq) OVER (PARTITION BY tp.lead_key) AS last_seq
    FROM fact_touchpoints tp
)
SELECT 
    j.touchpoint_key,
    j.lead_key,
    j.touch_seq,
    j.touch_date_key,
    j.channel_key,
    j.campaign_key,
    j.total_touches,
    -- First-Touch Weight
    CASE WHEN j.touch_seq = j.first_seq THEN 1.0 ELSE 0.0 END AS weight_first_touch,
    -- Last-Touch Weight
    CASE WHEN j.touch_seq = j.last_seq THEN 1.0 ELSE 0.0 END AS weight_last_touch,
    -- Linear Weight
    ROUND(1.0 / j.total_touches, 6) AS weight_linear,
    -- Position-Based (40-20-40) Weight
    ROUND(
        CASE 
            WHEN j.total_touches = 1 THEN 1.0
            WHEN j.total_touches = 2 THEN 0.5
            WHEN j.touch_seq = j.first_seq THEN 0.40
            WHEN j.touch_seq = j.last_seq  THEN 0.40
            ELSE 0.20 / (j.total_touches - 2)
        END, 6
    ) AS weight_position_based
FROM journey_meta j;

-- ---------------------------------------------------------------------
-- 2. VIEW: v_channel_attribution_comparison
-- Aggregates leads, enrollments, and revenue across the 4 models,
-- blending fact_spend to calculate model-adjusted CAC and ROAS.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_channel_attribution_comparison AS
WITH enrolled_leads AS (
    SELECT 
        lead_key, 
        converted_flag, 
        NVL(commission_inr, 0) AS commission_inr 
    FROM fact_leads
),
channel_spend AS (
    SELECT 
        c.channel_key,
        SUM(s.spend_inr) AS total_spend_inr
    FROM fact_spend s
    JOIN dim_campaign c ON s.campaign_key = c.campaign_key
    GROUP BY c.channel_key
),
weighted_touches AS (
    SELECT 
        w.channel_key,
        -- Attributed Leads
        SUM(w.weight_first_touch)      AS ft_leads,
        SUM(w.weight_last_touch)       AS lt_leads,
        SUM(w.weight_linear)           AS lin_leads,
        SUM(w.weight_position_based)   AS pb_leads,
        -- Attributed Enrollments
        SUM(w.weight_first_touch * el.converted_flag)    AS ft_enrollments,
        SUM(w.weight_last_touch * el.converted_flag)     AS lt_enrollments,
        SUM(w.weight_linear * el.converted_flag)         AS lin_enrollments,
        SUM(w.weight_position_based * el.converted_flag) AS pb_enrollments,
        -- Attributed Revenue
        SUM(w.weight_first_touch * el.commission_inr)    AS ft_revenue,
        SUM(w.weight_last_touch * el.commission_inr)     AS lt_revenue,
        SUM(w.weight_linear * el.commission_inr)         AS lin_revenue,
        SUM(w.weight_position_based * el.commission_inr) AS pb_revenue
    FROM v_touchpoint_weights w
    JOIN enrolled_leads el ON w.lead_key = el.lead_key
    GROUP BY w.channel_key
)
SELECT 
    ch.channel_name,
    ch.channel_group,
    ch.is_paid,
    NVL(sp.total_spend_inr, 0) AS total_spend_inr,
    -- First Touch Metrics
    ROUND(wt.ft_enrollments, 2) AS ft_enrollments,
    ROUND(wt.ft_revenue, 2)     AS ft_revenue,
    ROUND(CASE WHEN wt.ft_enrollments > 0 THEN sp.total_spend_inr / wt.ft_enrollments ELSE NULL END, 2) AS ft_cac,
    ROUND(CASE WHEN sp.total_spend_inr > 0 THEN wt.ft_revenue / sp.total_spend_inr ELSE NULL END, 3)    AS ft_roas,
    -- Last Touch Metrics
    ROUND(wt.lt_enrollments, 2) AS lt_enrollments,
    ROUND(wt.lt_revenue, 2)     AS lt_revenue,
    ROUND(CASE WHEN wt.lt_enrollments > 0 THEN sp.total_spend_inr / wt.lt_enrollments ELSE NULL END, 2) AS lt_cac,
    ROUND(CASE WHEN sp.total_spend_inr > 0 THEN wt.lt_revenue / sp.total_spend_inr ELSE NULL END, 3)    AS lt_roas,
    -- Linear Metrics
    ROUND(wt.lin_enrollments, 2) AS lin_enrollments,
    ROUND(wt.lin_revenue, 2)     AS lin_revenue,
    ROUND(CASE WHEN wt.lin_enrollments > 0 THEN sp.total_spend_inr / wt.lin_enrollments ELSE NULL END, 2) AS lin_cac,
    ROUND(CASE WHEN sp.total_spend_inr > 0 THEN wt.lin_revenue / sp.total_spend_inr ELSE NULL END, 3)    AS lin_roas,
    -- Position-Based Metrics
    ROUND(wt.pb_enrollments, 2) AS pb_enrollments,
    ROUND(wt.pb_revenue, 2)     AS pb_revenue,
    ROUND(CASE WHEN wt.pb_enrollments > 0 THEN sp.total_spend_inr / wt.pb_enrollments ELSE NULL END, 2) AS pb_cac,
    ROUND(CASE WHEN sp.total_spend_inr > 0 THEN wt.pb_revenue / sp.total_spend_inr ELSE NULL END, 3)    AS pb_roas
FROM weighted_touches wt
JOIN dim_channel ch ON wt.channel_key = ch.channel_key
LEFT JOIN channel_spend sp ON wt.channel_key = sp.channel_key
ORDER BY NVL(sp.total_spend_inr, 0) DESC, wt.lt_revenue DESC;


SELECT 
    channel_name,
    total_spend_inr,
    ft_roas,
    lt_roas,
    lin_roas,
    pb_roas,
    ft_cac,
    lt_cac,
    lin_cac,
    pb_cac
FROM v_channel_attribution_comparison
WHERE is_paid = 1
ORDER BY total_spend_inr DESC;