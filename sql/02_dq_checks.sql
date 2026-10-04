-- =====================================================================================
-- Day 2 data-quality checks. Run as FUNNEL_PRJ, after src/etl_load.py has loaded all
-- tables. Each query should return 0 rows / 0 for a clean load. Compare the defect
-- counts to data/synthetic/_injection_log.json (the ETL prints the same numbers).
-- =====================================================================================

-- 1. Row counts: sanity check load completeness
SELECT 'dim_channel' tbl, COUNT(*) rows FROM dim_channel
UNION ALL SELECT 'dim_campaign', COUNT(*) FROM dim_campaign
UNION ALL SELECT 'dim_course', COUNT(*) FROM dim_course
UNION ALL SELECT 'fact_leads', COUNT(*) FROM fact_leads
UNION ALL SELECT 'fact_touchpoints', COUNT(*) FROM fact_touchpoints
UNION ALL SELECT 'fact_spend', COUNT(*) FROM fact_spend;

-- 2. Duplicate prospects in fact_leads (uq_fact_leads_prospect should make this impossible,
--    this just double-checks the pre-load dedupe worked as intended)
SELECT prospect_id, COUNT(*) FROM fact_leads GROUP BY prospect_id HAVING COUNT(*) > 1;

-- 3. Any lead with no touchpoint at all? (every lead should have at least its last touch)
SELECT l.prospect_id
FROM fact_leads l
LEFT JOIN fact_touchpoints t ON t.lead_key = l.lead_key
WHERE t.lead_key IS NULL;

-- 4. Leads whose campaign could not be resolved to a real campaign (landed in '(unmapped)')
--    Expect this count to equal "paid_leads_with_missing_campaign" in the ETL's printed log.
SELECT COUNT(*) AS unmapped_campaign_leads
FROM fact_leads l JOIN dim_campaign c ON c.campaign_key = l.campaign_key
WHERE c.campaign_id = '(unmapped)';

-- 5. Business-rule spot check: every enrolled lead must have a commission and an
--    enrollment date that is on/after its created date (the DB CHECK constraint already
--    enforces the first two at load time; this adds the date-order check).
SELECT l.prospect_id, l.created_date_key, l.enrollment_date_key
FROM fact_leads l
WHERE l.converted_flag = 1
  AND l.enrollment_date_key < l.created_date_key;

-- 6. Funnel stage sanity: max_stage_key must be between 1 and 5 for every lead
--    (enforced by the FK to dim_stage, this just surfaces any that slipped through)
SELECT l.prospect_id, l.max_stage_key
FROM fact_leads l
LEFT JOIN dim_stage s ON s.stage_key = l.max_stage_key
WHERE s.stage_key IS NULL;

-- 7. Spend sanity: clicks should never exceed impressions (CHECK constraint enforces this
--    at load, so this should always return 0 rows if the load succeeded)
SELECT * FROM fact_spend WHERE clicks > impressions;

-- 8. Touchpoint ordering: touch_seq = 1 must be the earliest date within each lead's journey
SELECT lead_key
FROM (
  SELECT lead_key, touch_seq, touch_date_key,
         MIN(touch_date_key) OVER (PARTITION BY lead_key) AS min_date
  FROM fact_touchpoints
)
WHERE touch_seq = 1 AND touch_date_key <> min_date;

-- 9. Channel mix overview: quick plausibility check on the loaded data (not a defect test)
SELECT ch.channel_name, ch.is_paid, COUNT(*) leads,
       SUM(l.converted_flag) enrollments,
       ROUND(100 * SUM(l.converted_flag) / COUNT(*), 1) AS conv_rate_pct
FROM fact_leads l JOIN dim_channel ch ON ch.channel_key = l.source_channel_key
GROUP BY ch.channel_name, ch.is_paid
ORDER BY leads DESC;
