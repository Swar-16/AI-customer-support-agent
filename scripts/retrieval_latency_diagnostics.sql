\pset pager off
\pset border 2
\pset null '[NULL]'
\timing on

\echo ''
\echo '============================================================'
\echo '1. RETRIEVAL LATENCY'
\echo '============================================================'

SELECT
    COUNT(*) AS successful_runs,
    ROUND(AVG(total_latency_ms)::numeric, 2) AS avg_total_ms,
    ROUND(
        PERCENTILE_CONT(0.50)
        WITHIN GROUP (ORDER BY total_latency_ms)::numeric,
        2
    ) AS p50_total_ms,
    ROUND(
        PERCENTILE_CONT(0.95)
        WITHIN GROUP (ORDER BY total_latency_ms)::numeric,
        2
    ) AS p95_total_ms,
    MIN(total_latency_ms) AS min_total_ms,
    MAX(total_latency_ms) AS max_total_ms,
    ROUND(AVG(vector_latency_ms)::numeric, 2) AS avg_vector_ms,
    ROUND(AVG(lexical_latency_ms)::numeric, 2) AS avg_lexical_ms,
    ROUND(AVG(fusion_latency_ms)::numeric, 2) AS avg_fusion_ms,
    ROUND(AVG(reranker_latency_ms)::numeric, 2) AS avg_reranker_ms,
    ROUND(AVG(context_build_latency_ms)::numeric, 2)
        AS avg_context_build_ms
FROM ai.retrieval_runs
WHERE status = 'success';


\echo ''
\echo '============================================================'
\echo '2. CANDIDATE AND CONTEXT COUNTS'
\echo '============================================================'

SELECT
    COUNT(*) AS successful_runs,
    ROUND(AVG(vector_candidate_count)::numeric, 2)
        AS avg_vector_candidates,
    ROUND(AVG(lexical_candidate_count)::numeric, 2)
        AS avg_lexical_candidates,
    ROUND(AVG(fused_candidate_count)::numeric, 2)
        AS avg_fused_candidates,
    ROUND(AVG(reranked_candidate_count)::numeric, 2)
        AS avg_reranked_candidates,
    ROUND(AVG(selected_candidate_count)::numeric, 2)
        AS avg_selected_candidates,
    ROUND(AVG(context_block_count)::numeric, 2)
        AS avg_context_blocks,
    ROUND(AVG(context_token_count)::numeric, 2)
        AS avg_context_tokens,
    MAX(context_token_count) AS max_context_tokens,
    COUNT(*) FILTER (WHERE context_truncated)
        AS truncated_contexts,
    COUNT(*) FILTER (WHERE zero_result)
        AS zero_result_runs
FROM ai.retrieval_runs
WHERE status = 'success';


\echo ''
\echo '============================================================'
\echo '3. TEN SLOWEST RETRIEVAL RUNS'
\echo '============================================================'

SELECT
    id,
    total_latency_ms,
    vector_latency_ms,
    lexical_latency_ms,
    fusion_latency_ms,
    reranker_latency_ms,
    context_build_latency_ms,
    vector_candidate_count,
    lexical_candidate_count,
    fused_candidate_count,
    selected_candidate_count,
    context_block_count,
    context_token_count,
    context_truncated,
    zero_result,
    started_at
FROM ai.retrieval_runs
WHERE status = 'success'
ORDER BY total_latency_ms DESC
LIMIT 10;


\echo ''
\echo '============================================================'
\echo '4. EMBEDDING LATENCY BY PURPOSE'
\echo '============================================================'

SELECT
    purpose,
    provider,
    model,
    status,
    COUNT(*) AS calls,
    ROUND(AVG(latency_ms)::numeric, 2) AS avg_ms,
    ROUND(
        PERCENTILE_CONT(0.50)
        WITHIN GROUP (ORDER BY latency_ms)::numeric,
        2
    ) AS p50_ms,
    ROUND(
        PERCENTILE_CONT(0.95)
        WITHIN GROUP (ORDER BY latency_ms)::numeric,
        2
    ) AS p95_ms,
    MAX(latency_ms) AS max_ms,
    ROUND(AVG(input_count)::numeric, 2) AS avg_inputs,
    ROUND(AVG(total_input_characters)::numeric, 2)
        AS avg_input_characters
FROM ai.embedding_calls
GROUP BY purpose, provider, model, status
ORDER BY calls DESC;


\echo ''
\echo '============================================================'
\echo '5. REPEATED EMBEDDING REQUESTS'
\echo '============================================================'

SELECT
    request_fingerprint,
    provider,
    model,
    purpose,
    COUNT(*) AS occurrence_count,
    ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency_ms,
    MIN(started_at) AS first_occurrence,
    MAX(started_at) AS latest_occurrence
FROM ai.embedding_calls
WHERE status = 'success'
  AND request_fingerprint IS NOT NULL
GROUP BY request_fingerprint, provider, model, purpose
HAVING COUNT(*) > 1
ORDER BY occurrence_count DESC, latest_occurrence DESC
LIMIT 30;


\echo ''
\echo '============================================================'
\echo '6. RETRIEVAL FAILURE SUMMARY'
\echo '============================================================'

SELECT
    status,
    error_code,
    metadata ->> 'timeout' AS timeout,
    COUNT(*) AS occurrence_count,
    MAX(completed_at) AS latest_occurrence
FROM ai.retrieval_runs
WHERE status <> 'success'
GROUP BY status, error_code, metadata ->> 'timeout'
ORDER BY occurrence_count DESC;


\echo ''
\echo 'DIAGNOSTICS COMPLETE'


-- How to Run this SQL FILE
-- $env:PGPASSWORD = "<your-actual-database-password>"
-- psql -h localhost -p 5432 -U support_ai_admin -d support_ai -X -v ON_ERROR_STOP=0 -f scripts/retrieval_latency_diagnostics.sql 2>&1 |  Out-File -FilePath retrieval_latency_output.txt -Encoding utf8