\pset pager off
\pset border 2
\pset null '[NULL]'
\timing on

\echo ''
\echo '============================================================'
\echo 'RECENT QUERY EMBEDDING CALLS'
\echo '============================================================'

SELECT
    id,
    ai_run_id,
    request_fingerprint,
    provider,
    model,
    latency_ms,
    status,
    started_at
FROM ai.embedding_calls
WHERE purpose = 'query'
ORDER BY started_at DESC
LIMIT 10;


\echo ''
\echo '============================================================'
\echo 'RECENT RETRIEVAL RUNS'
\echo '============================================================'

SELECT
    id,
    ai_run_id,
    embedding_call_id,
    vector_latency_ms,
    lexical_latency_ms,
    fusion_latency_ms,
    context_build_latency_ms,
    total_latency_ms,
    context_block_count,
    context_token_count,
    status,
    started_at
FROM ai.retrieval_runs
ORDER BY started_at DESC
LIMIT 10;


\echo ''
\echo '============================================================'
\echo 'CACHE VERIFICATION SUMMARY'
\echo '============================================================'

WITH recent_retrievals AS (
    SELECT *
    FROM ai.retrieval_runs
    WHERE started_at >= NOW() - INTERVAL '30 minutes'
      AND status = 'success'
),
recent_embeddings AS (
    SELECT *
    FROM ai.embedding_calls
    WHERE started_at >= NOW() - INTERVAL '30 minutes'
      AND purpose = 'query'
      AND status = 'success'
)
SELECT
    (SELECT COUNT(*) FROM recent_retrievals)
        AS retrieval_runs,

    (SELECT COUNT(*) FROM recent_embeddings)
        AS external_embedding_calls,

    (
        SELECT COUNT(*)
        FROM recent_retrievals
        WHERE embedding_call_id IS NULL
    ) AS probable_cache_hits,

    ROUND(
        (
            SELECT AVG(vector_latency_ms)::numeric
            FROM recent_retrievals
            WHERE embedding_call_id IS NOT NULL
        ),
        2
    ) AS avg_cache_miss_vector_ms,

    ROUND(
        (
            SELECT AVG(vector_latency_ms)::numeric
            FROM recent_retrievals
            WHERE embedding_call_id IS NULL
        ),
        2
    ) AS avg_cache_hit_vector_ms;

-- How to Run this SQL FILE
-- $env:PGPASSWORD = "<your-actual-database-password>"
-- psql -h localhost -p 5432 -U support_ai_admin -d support_ai -X -v ON_ERROR_STOP=1 -f scripts/verify_embedding_cache.sql 2>&1 | Out-File -FilePath embedding_cache_verification.txt -Encoding utf8