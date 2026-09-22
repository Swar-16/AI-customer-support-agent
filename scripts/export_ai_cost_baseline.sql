\set ON_ERROR_STOP on
\set QUIET 1
\pset pager off
\pset footer off
\pset null '[null]'
\pset border 1
\pset linestyle ascii
\set QUIET 0

-- Read-only AI cost, quota, latency, and routing baseline.
-- Change this value when a different observation window is required.
\set lookback_days 30

BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '60s';
SET LOCAL lock_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '90s';
SET LOCAL TIME ZONE 'UTC';

\echo 'AI COST AND QUOTA BASELINE'
SELECT current_database() AS database_name,
       current_user AS database_user,
       current_timestamp AS generated_at_utc,
       :lookback_days::integer AS lookback_days,
       current_timestamp - make_interval(days => :lookback_days::integer) AS window_start_utc;

\echo ''
\echo '1. TELEMETRY INVENTORY (all time)'
SELECT 'ai.runs' AS relation, count(*) AS row_count, min(started_at) AS earliest_at, max(started_at) AS latest_at FROM ai.runs
UNION ALL
SELECT 'ai.llm_calls', count(*), min(started_at), max(started_at) FROM ai.llm_calls
UNION ALL
SELECT 'ai.intent_predictions', count(*), min(created_at), max(created_at) FROM ai.intent_predictions
UNION ALL
SELECT 'ai.decisions', count(*), min(created_at), max(created_at) FROM ai.decisions
UNION ALL
SELECT 'ai.stage_events', count(*), min(occurred_at), max(occurred_at) FROM ai.stage_events
ORDER BY relation;

\echo ''
\echo '2. LLM USAGE BY PURPOSE, PROVIDER, MODEL, AND STATUS'
SELECT purpose,
       provider,
       model,
       status,
       count(*) AS calls,
       count(DISTINCT ai_run_id) AS runs,
       sum(input_tokens) AS input_tokens,
       sum(output_tokens) AS output_tokens,
       sum(cached_input_tokens) AS cached_input_tokens,
       sum(total_tokens) AS total_tokens,
       round(avg(input_tokens), 2) AS avg_input_tokens,
       round(avg(output_tokens), 2) AS avg_output_tokens,
       round(avg(latency_ms), 2) AS avg_latency_ms,
       round(sum(estimated_cost_usd), 8) AS recorded_cost_usd
FROM ai.llm_calls
WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
GROUP BY purpose, provider, model, status
ORDER BY total_tokens DESC NULLS LAST, calls DESC, purpose, provider, model, status;

\echo ''
\echo '3. PURPOSE SUMMARY WITH SUCCESS, FAILURE, AND TOKEN SHARES'
WITH purpose_usage AS (
    SELECT purpose,
           count(*) AS calls,
           count(*) FILTER (WHERE status = 'success') AS successful_calls,
           count(*) FILTER (WHERE status IN ('failed', 'timeout')) AS failed_or_timed_out_calls,
           sum(input_tokens) AS input_tokens,
           sum(output_tokens) AS output_tokens,
           sum(cached_input_tokens) AS cached_input_tokens,
           sum(total_tokens) AS total_tokens,
           sum(estimated_cost_usd) AS cost_usd
    FROM ai.llm_calls
    WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
    GROUP BY purpose
), totals AS (
    SELECT sum(calls) AS calls, sum(total_tokens) AS total_tokens, sum(cost_usd) AS cost_usd
    FROM purpose_usage
)
SELECT p.*,
       round(100.0 * p.calls / nullif(t.calls, 0), 2) AS call_share_pct,
       round(100.0 * p.total_tokens / nullif(t.total_tokens, 0), 2) AS token_share_pct,
       round(100.0 * p.cost_usd / nullif(t.cost_usd, 0), 2) AS cost_share_pct
FROM purpose_usage p
CROSS JOIN totals t
ORDER BY p.total_tokens DESC NULLS LAST, p.calls DESC, p.purpose;

\echo ''
\echo '4. LLM CALLS AND TOKENS PER AI RUN'
WITH per_run AS (
    SELECT r.id AS ai_run_id,
           r.status AS run_status,
           count(c.id) AS llm_calls,
           count(c.id) FILTER (WHERE c.status = 'success') AS successful_llm_calls,
           coalesce(sum(c.input_tokens), 0) AS input_tokens,
           coalesce(sum(c.output_tokens), 0) AS output_tokens,
           coalesce(sum(c.total_tokens), 0) AS total_tokens,
           coalesce(sum(c.estimated_cost_usd), 0) AS cost_usd
    FROM ai.runs r
    LEFT JOIN ai.llm_calls c ON c.ai_run_id = r.id
    WHERE r.started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
    GROUP BY r.id, r.status
)
SELECT count(*) AS runs,
       round(avg(llm_calls), 3) AS avg_calls_per_run,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY llm_calls) AS p50_calls_per_run,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY llm_calls) AS p95_calls_per_run,
       max(llm_calls) AS max_calls_per_run,
       round(avg(total_tokens), 2) AS avg_tokens_per_run,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY total_tokens) AS p50_tokens_per_run,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY total_tokens) AS p95_tokens_per_run,
       max(total_tokens) AS max_tokens_per_run,
       round(sum(cost_usd), 8) AS recorded_cost_usd
FROM per_run;

\echo ''
\echo '5. DISTRIBUTION OF LLM CALL COUNT PER AI RUN'
WITH per_run AS (
    SELECT r.id, count(c.id) AS llm_calls
    FROM ai.runs r
    LEFT JOIN ai.llm_calls c ON c.ai_run_id = r.id
    WHERE r.started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
    GROUP BY r.id
)
SELECT llm_calls, count(*) AS runs,
       round(100.0 * count(*) / nullif(sum(count(*)) OVER (), 0), 2) AS runs_pct
FROM per_run
GROUP BY llm_calls
ORDER BY llm_calls;

\echo ''
\echo '6. TITLE-GENERATION OVERHEAD'
WITH totals AS (
    SELECT count(*) AS calls,
           sum(total_tokens) AS total_tokens,
           sum(estimated_cost_usd) AS cost_usd
    FROM ai.llm_calls
    WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
), titles AS (
    SELECT count(*) AS calls,
           sum(total_tokens) AS total_tokens,
           sum(estimated_cost_usd) AS cost_usd,
           count(DISTINCT ai_run_id) AS affected_runs
    FROM ai.llm_calls
    WHERE purpose = 'conversation_title'
      AND started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
)
SELECT titles.calls AS title_calls,
       titles.affected_runs,
       titles.total_tokens AS title_tokens,
       round(titles.cost_usd, 8) AS title_cost_usd,
       round(100.0 * titles.calls / nullif(totals.calls, 0), 2) AS all_calls_pct,
       round(100.0 * titles.total_tokens / nullif(totals.total_tokens, 0), 2) AS all_tokens_pct,
       round(100.0 * titles.cost_usd / nullif(totals.cost_usd, 0), 2) AS all_cost_pct
FROM titles CROSS JOIN totals;

\echo ''
\echo '7. LATENCY PERCENTILES BY PURPOSE (finalized calls only)'
SELECT purpose,
       count(*) AS calls,
       round(avg(latency_ms), 2) AS avg_ms,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,
       percentile_cont(0.90) WITHIN GROUP (ORDER BY latency_ms) AS p90_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99_ms,
       max(latency_ms) AS max_ms
FROM ai.llm_calls
WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
  AND latency_ms IS NOT NULL
GROUP BY purpose
ORDER BY p95_ms DESC NULLS LAST, purpose;

\echo ''
\echo '8. FAILURES AND TIMEOUTS (no error-message text exported)'
SELECT purpose,
       provider,
       model,
       status,
       coalesce(error_code, '[none]') AS error_code,
       count(*) AS occurrences,
       min(started_at) AS first_seen_at,
       max(started_at) AS last_seen_at
FROM ai.llm_calls
WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
  AND status IN ('failed', 'timeout')
GROUP BY purpose, provider, model, status, coalesce(error_code, '[none]')
ORDER BY occurrences DESC, purpose, status, error_code;

\echo ''
\echo '9. CACHE UTILIZATION'
SELECT purpose,
       count(*) AS calls,
       count(*) FILTER (WHERE cached_input_tokens > 0) AS calls_with_cached_input,
       sum(input_tokens) AS input_tokens,
       sum(cached_input_tokens) AS cached_input_tokens,
       round(100.0 * sum(cached_input_tokens) / nullif(sum(input_tokens), 0), 2) AS cached_vs_input_pct
FROM ai.llm_calls
WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
GROUP BY purpose
ORDER BY input_tokens DESC NULLS LAST, purpose;

\echo ''
\echo '10. DAILY REQUEST, TOKEN, COST, AND ERROR TREND'
SELECT date_trunc('day', started_at) AS day_utc,
       count(*) AS calls,
       count(DISTINCT ai_run_id) AS runs,
       count(*) FILTER (WHERE status IN ('failed', 'timeout')) AS failed_or_timed_out_calls,
       sum(input_tokens) AS input_tokens,
       sum(output_tokens) AS output_tokens,
       sum(total_tokens) AS total_tokens,
       round(sum(estimated_cost_usd), 8) AS recorded_cost_usd
FROM ai.llm_calls
WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
GROUP BY date_trunc('day', started_at)
ORDER BY day_utc;

\echo ''
\echo '11. PEAK OBSERVED ONE-MINUTE PROVIDER LOAD'
WITH per_minute AS (
    SELECT date_trunc('minute', started_at) AS minute_utc,
           provider,
           model,
           count(*) AS rpm,
           sum(total_tokens) AS tpm,
           sum(input_tokens) AS input_tpm,
           sum(output_tokens) AS output_tpm
    FROM ai.llm_calls
    WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
    GROUP BY date_trunc('minute', started_at), provider, model
), ranked AS (
    SELECT *,
           row_number() OVER (PARTITION BY provider, model ORDER BY rpm DESC, minute_utc DESC) AS rpm_rank,
           row_number() OVER (PARTITION BY provider, model ORDER BY tpm DESC, minute_utc DESC) AS tpm_rank
    FROM per_minute
)
SELECT provider, model, minute_utc, rpm, tpm, input_tpm, output_tpm,
       CASE WHEN rpm_rank = 1 THEN 'peak_rpm' ELSE 'peak_tpm' END AS peak_type
FROM ranked
WHERE rpm_rank = 1 OR tpm_rank = 1
ORDER BY provider, model, peak_type;

\echo ''
\echo '12. AI RUN STATUS AND END-TO-END LATENCY'
SELECT status,
       count(*) AS runs,
       round(avg(total_latency_ms), 2) AS avg_latency_ms,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY total_latency_ms) AS p50_latency_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_latency_ms,
       max(total_latency_ms) AS max_latency_ms
FROM ai.runs
WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
GROUP BY status
ORDER BY runs DESC, status;

\echo ''
\echo '13. INTENT ROUTING SUMMARY (no entities or reasoning exported)'
SELECT intent,
       count(*) AS predictions,
       round(avg(confidence), 4) AS avg_confidence,
       count(*) FILTER (WHERE needs_clarification) AS clarification_predictions,
       count(*) FILTER (WHERE jsonb_array_length(escalation_signals) > 0) AS predictions_with_escalation_signal,
       count(*) FILTER (WHERE llm_call_id IS NULL) AS predictions_without_llm_call
FROM ai.intent_predictions
WHERE created_at >= current_timestamp - make_interval(days => :lookback_days::integer)
GROUP BY intent
ORDER BY predictions DESC, intent;

\echo ''
\echo '14. DECISION ROUTING SUMMARY (no summaries or metadata exported)'
SELECT decision_type,
       coalesce(reason_code, '[none]') AS reason_code,
       count(*) AS decisions,
       round(avg(confidence), 4) AS avg_confidence,
       count(*) FILTER (WHERE llm_call_id IS NULL) AS deterministic_decisions
FROM ai.decisions
WHERE created_at >= current_timestamp - make_interval(days => :lookback_days::integer)
GROUP BY decision_type, coalesce(reason_code, '[none]')
ORDER BY decisions DESC, decision_type, reason_code;

\echo ''
\echo '15. ORCHESTRATION STAGE LATENCY AND FAILURES'
SELECT stage,
       count(*) FILTER (WHERE event_type = 'stage_completed') AS completed_events,
       count(*) FILTER (WHERE event_type = 'stage_failed') AS failed_events,
       round(avg(duration_ms) FILTER (WHERE event_type IN ('stage_completed', 'stage_failed')), 2) AS avg_duration_ms,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms)
           FILTER (WHERE event_type IN ('stage_completed', 'stage_failed') AND duration_ms IS NOT NULL) AS p50_duration_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
           FILTER (WHERE event_type IN ('stage_completed', 'stage_failed') AND duration_ms IS NOT NULL) AS p95_duration_ms,
       max(duration_ms) AS max_duration_ms
FROM ai.stage_events
WHERE occurred_at >= current_timestamp - make_interval(days => :lookback_days::integer)
GROUP BY stage
ORDER BY p95_duration_ms DESC NULLS LAST, stage;

\echo ''
\echo '16. STAGE FAILURE CODES'
SELECT stage,
       coalesce(error_code, '[none]') AS error_code,
       retryable,
       count(*) AS failures
FROM ai.stage_events
WHERE occurred_at >= current_timestamp - make_interval(days => :lookback_days::integer)
  AND event_type = 'stage_failed'
GROUP BY stage, coalesce(error_code, '[none]'), retryable
ORDER BY failures DESC, stage, error_code;

\echo ''
\echo '17. TELEMETRY DATA-QUALITY CHECKS'
SELECT 'stale_started_calls_over_10_minutes' AS check_name, count(*) AS affected_rows
FROM ai.llm_calls
WHERE status = 'started' AND started_at < current_timestamp - interval '10 minutes'
UNION ALL
SELECT 'final_calls_without_completed_at', count(*)
FROM ai.llm_calls
WHERE status IN ('success', 'failed', 'timeout') AND completed_at IS NULL
UNION ALL
SELECT 'successful_calls_without_latency', count(*)
FROM ai.llm_calls
WHERE status = 'success' AND latency_ms IS NULL
UNION ALL
SELECT 'successful_calls_with_zero_total_tokens', count(*)
FROM ai.llm_calls
WHERE status = 'success' AND total_tokens = 0
UNION ALL
SELECT 'token_total_mismatch', count(*)
FROM ai.llm_calls
WHERE total_tokens <> input_tokens + output_tokens
UNION ALL
SELECT 'cached_tokens_greater_than_input', count(*)
FROM ai.llm_calls
WHERE cached_input_tokens > input_tokens
UNION ALL
SELECT 'runs_without_llm_calls', count(*)
FROM ai.runs r
WHERE r.started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
  AND NOT EXISTS (SELECT 1 FROM ai.llm_calls c WHERE c.ai_run_id = r.id)
UNION ALL
SELECT 'intent_predictions_without_llm_link', count(*)
FROM ai.intent_predictions
WHERE created_at >= current_timestamp - make_interval(days => :lookback_days::integer)
  AND llm_call_id IS NULL
ORDER BY check_name;

\echo ''
\echo '18. PROMPT-VERSION ATTRIBUTION COVERAGE'
SELECT purpose,
       count(*) AS calls,
       count(*) FILTER (WHERE prompt_version_id IS NOT NULL) AS calls_with_prompt_version,
       count(*) FILTER (WHERE prompt_version_id IS NULL) AS calls_without_prompt_version,
       round(100.0 * count(*) FILTER (WHERE prompt_version_id IS NOT NULL) / nullif(count(*), 0), 2) AS coverage_pct
FROM ai.llm_calls
WHERE started_at >= current_timestamp - make_interval(days => :lookback_days::integer)
GROUP BY purpose
ORDER BY calls DESC, purpose;

ROLLBACK;
\echo ''
\echo 'END OF READ-ONLY BASELINE'


-- How to Run this SQL FILE
-- $env:PGPASSWORD = "<your-actual-database-password>"
-- psql -h localhost -p 5432 -U support_ai_admin -d support_ai -X -v ON_ERROR_STOP=1 -f "scripts\export_ai_cost_baseline.sql" 2>&1 | Tee-Object -FilePath ".\ai_cost_baseline_output.txt"