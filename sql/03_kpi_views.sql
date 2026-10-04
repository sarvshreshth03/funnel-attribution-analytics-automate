-- =====================================================================
-- Day 3: KPI Views, Funnel Drop-off & Cohort Analysis
-- Schema: FUNNEL_PRJ
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. VIEW: v_daily_channel_kpis
-- Blends spend, leads, enrollments, and revenue at day + channel level.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_daily_channel_kpis AS
WITH spend_agg AS (
    SELECT 
        s.date_key,
        c.channel_key,
        SUM(s.impressions) AS impressions,
        SUM(s.clicks)      AS clicks,
        SUM(s.spend_inr)   AS spend_inr
    FROM fact_spend s
    JOIN dim_campaign c ON s.campaign_key = c.campaign_key
    GROUP BY s.date_key, c.channel_key
),
leads_agg AS (
    SELECT 
        created_date_key                       AS date_key,
        source_channel_key                     AS channel_key,
        COUNT(lead_key)                        AS leads_generated,
        SUM(CASE WHEN converted_flag = 1 THEN 1 ELSE 0 END) AS conversions_acquired,
        SUM(NVL(commission_inr, 0))            AS pipeline_commission_inr
    FROM fact_leads
    GROUP BY created_date_key, source_channel_key
),
all_keys AS (
    SELECT date_key, channel_key FROM spend_agg
    UNION
    SELECT date_key, channel_key FROM leads_agg
)
SELECT 
    k.date_key,
    d.full_date,
    d.week_start_date,
    d.month_start_date,
    ch.channel_key,
    ch.channel_name,
    ch.channel_group,
    ch.is_paid,
    NVL(s.impressions, 0) AS impressions,
    NVL(s.clicks, 0)      AS clicks,
    NVL(s.spend_inr, 0)   AS spend_inr,
    NVL(l.leads_generated, 0) AS leads_generated,
    NVL(l.conversions_acquired, 0) AS enrollments,
    NVL(l.pipeline_commission_inr, 0) AS revenue_inr,
    -- CPL (Cost Per Lead)
    ROUND(
        CASE WHEN NVL(l.leads_generated, 0) > 0 
             THEN NVL(s.spend_inr, 0) / l.leads_generated 
             ELSE NULL 
        END, 2
    ) AS cpl_inr,
    -- CAC (Customer Acquisition Cost)
    ROUND(
        CASE WHEN NVL(l.conversions_acquired, 0) > 0 
             THEN NVL(s.spend_inr, 0) / l.conversions_acquired 
             ELSE NULL 
        END, 2
    ) AS cac_inr,
    -- ROAS (Return on Ad Spend)
    ROUND(
        CASE WHEN NVL(s.spend_inr, 0) > 0 
             THEN NVL(l.pipeline_commission_inr, 0) / s.spend_inr 
             ELSE NULL 
        END, 4
    ) AS roas
FROM all_keys k
JOIN dim_date d      ON k.date_key = d.date_key
JOIN dim_channel ch  ON k.channel_key = ch.channel_key
LEFT JOIN spend_agg s ON k.date_key = s.date_key AND k.channel_key = s.channel_key
LEFT JOIN leads_agg l ON k.date_key = l.date_key AND k.channel_key = l.channel_key;

-- ---------------------------------------------------------------------
-- 2. VIEW: v_funnel_stage_conversion
-- Calculates cumulative volume reaching each stage and step-to-step drop-off.
-- In our schema, max_stage_key = N means the lead achieved all stages <= N.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_funnel_stage_conversion AS
WITH stage_counts AS (
    SELECT 
        l.source_channel_key,
        l.course_key,
        COUNT(l.lead_key) AS stage_1_captured,
        SUM(CASE WHEN l.max_stage_key >= 2 THEN 1 ELSE 0 END) AS stage_2_contacted,
        SUM(CASE WHEN l.max_stage_key >= 3 THEN 1 ELSE 0 END) AS stage_3_qualified,
        SUM(CASE WHEN l.max_stage_key >= 4 THEN 1 ELSE 0 END) AS stage_4_applied,
        SUM(CASE WHEN l.max_stage_key >= 5 THEN 1 ELSE 0 END) AS stage_5_enrolled
    FROM fact_leads l
    GROUP BY l.source_channel_key, l.course_key
)
SELECT 
    ch.channel_name,
    ch.channel_group,
    co.specialization,
    s.stage_1_captured,
    s.stage_2_contacted,
    ROUND(s.stage_2_contacted * 100.0 / NULLIF(s.stage_1_captured, 0), 2) AS pct_captured_to_contacted,
    s.stage_3_qualified,
    ROUND(s.stage_3_qualified * 100.0 / NULLIF(s.stage_2_contacted, 0), 2) AS pct_contacted_to_qualified,
    s.stage_4_applied,
    ROUND(s.stage_4_applied * 100.0 / NULLIF(s.stage_3_qualified, 0), 2) AS pct_qualified_to_applied,
    s.stage_5_enrolled,
    ROUND(s.stage_5_enrolled * 100.0 / NULLIF(s.stage_4_applied, 0), 2) AS pct_applied_to_enrolled,
    -- Overall Funnel Conversion Rate
    ROUND(s.stage_5_enrolled * 100.0 / NULLIF(s.stage_1_captured, 0), 2) AS overall_conversion_rate
FROM stage_counts s
JOIN dim_channel ch ON s.source_channel_key = ch.channel_key
JOIN dim_course co   ON s.course_key = co.course_key;

-- ---------------------------------------------------------------------
-- 3. VIEW: v_cohort_lead_to_enrollment
-- Analyzes lead conversion grouped by acquisition week.
-- Matured flag identifies cohorts where the 60-day lag window has elapsed.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_cohort_lead_to_enrollment AS
WITH max_created AS (
    SELECT MAX(d.full_date) AS max_dataset_date
    FROM fact_leads l
    JOIN dim_date d ON l.created_date_key = d.date_key
),
cohort_base AS (
    SELECT 
        d.year_num,
        d.week_start_date,
        COUNT(l.lead_key) AS cohort_leads,
        SUM(CASE WHEN l.converted_flag = 1 THEN 1 ELSE 0 END) AS enrollments,
        ROUND(AVG(
            CASE WHEN l.converted_flag = 1 
                 THEN (TO_DATE(TO_CHAR(l.enrollment_date_key), 'YYYYMMDD') - TO_DATE(TO_CHAR(l.created_date_key), 'YYYYMMDD'))
                 ELSE NULL 
            END
        ), 1) AS avg_days_to_enroll,
        SUM(NVL(l.commission_inr, 0)) AS cohort_commission_inr,
        -- A cohort is matured if week_start_date + 60 days <= max_dataset_date
        CASE 
            WHEN d.week_start_date + 60 <= m.max_dataset_date THEN 'MATURED'
            ELSE 'MATURING'
        END AS cohort_status
    FROM fact_leads l
    JOIN dim_date d ON l.created_date_key = d.date_key
    CROSS JOIN max_created m
    GROUP BY d.year_num, d.week_start_date, m.max_dataset_date
)
SELECT 
    year_num,
    week_start_date,
    cohort_status,
    cohort_leads,
    enrollments,
    ROUND(enrollments * 100.0 / NULLIF(cohort_leads, 0), 2) AS conversion_rate_pct,
    avg_days_to_enroll,
    cohort_commission_inr,
    ROUND(cohort_commission_inr / NULLIF(cohort_leads, 0), 2) AS rev_per_lead_inr
FROM cohort_base
ORDER BY week_start_date ASC;

SELECT 
    channel_group,
    SUM(stage_1_captured)  AS total_leads,
    SUM(stage_2_contacted) AS contacted,
    SUM(stage_3_qualified) AS qualified,
    SUM(stage_4_applied)   AS applied,
    SUM(stage_5_enrolled)  AS enrolled,
    ROUND(SUM(stage_5_enrolled) * 100.0 / NULLIF(SUM(stage_1_captured), 0), 2) AS overall_conversion_pct
FROM v_funnel_stage_conversion
GROUP BY channel_group
ORDER BY total_leads DESC;

SELECT 
    cohort_status,
    COUNT(*) AS total_weeks,
    SUM(cohort_leads) AS total_leads,
    SUM(enrollments) AS total_enrollments,
    ROUND(SUM(enrollments) * 100.0 / NULLIF(SUM(cohort_leads), 0), 2) AS blended_conversion_pct,
    ROUND(AVG(avg_days_to_enroll), 1) AS avg_days_to_enroll,
    ROUND(SUM(cohort_commission_inr), 2) AS total_commission_inr,
    ROUND(SUM(cohort_commission_inr) / NULLIF(SUM(cohort_leads), 0), 2) AS avg_rev_per_lead
FROM v_cohort_lead_to_enrollment
GROUP BY cohort_status
ORDER BY cohort_status DESC;

SELECT 
    channel_name,
    channel_group,
    SUM(impressions)         AS total_impressions,
    SUM(clicks)              AS total_clicks,
    SUM(spend_inr)           AS total_spend,
    SUM(leads_generated)     AS total_leads,
    SUM(enrollments)         AS total_enrollments,
    SUM(revenue_inr)         AS total_revenue,
    ROUND(SUM(spend_inr) / NULLIF(SUM(leads_generated), 0), 2) AS blended_cpl,
    ROUND(SUM(spend_inr) / NULLIF(SUM(enrollments), 0), 2)     AS blended_cac,
    ROUND(SUM(revenue_inr) / NULLIF(SUM(spend_inr), 0), 2)     AS blended_roas
FROM v_daily_channel_kpis
WHERE is_paid = 1
GROUP BY channel_name, channel_group
ORDER BY total_spend DESC;