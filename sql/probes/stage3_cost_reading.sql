-- Stage 3 cost reading. Read-only (SELECT on ACCOUNT_USAGE). Run in Snowsight as
-- ACCOUNTADMIN, or any role that can read SNOWFLAKE.ACCOUNT_USAGE.
-- Covers the Stage 3 live run (2026-11-05) and whether LESSON_SEARCH kept serving
-- after the Stage 1 teardown (it answered "already resumed" on 2026-11-05).
-- Serving is billed while the service is available, even with no queries:
-- https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/cortex-search-costs
-- https://docs.snowflake.com/en/sql-reference/account-usage/cortex_search_daily_usage_history

USE ROLE ACCOUNTADMIN;

-- 1. AI function credits per day and model since Stage 1.
SELECT DATE_TRUNC('day', START_TIME)       AS day,
       FUNCTION_NAME,
       MODEL_NAME,
       COUNT(DISTINCT QUERY_ID)            AS queries,
       ROUND(SUM(CREDITS), 4)              AS ai_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
WHERE START_TIME >= '2026-11-04'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

-- 2. Warehouse credits per day since Stage 1 (lags up to 3 hours).
SELECT DATE_TRUNC('day', START_TIME) AS day, WAREHOUSE_NAME,
       ROUND(SUM(CREDITS_USED), 4)   AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE START_TIME >= '2026-11-04'
GROUP BY 1, 2
ORDER BY 1, 2;

-- 3. Cortex Search credits per day and type (SERVING / EMBED_TEXT_TOKENS / BATCH).
--    SERVING rows on days between the Stage 1 teardown and 2026-11-05 mean the
--    service was not suspended.
SELECT USAGE_DATE, SERVICE_NAME, CONSUMPTION_TYPE,
       ROUND(SUM(CREDITS), 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
WHERE USAGE_DATE >= '2026-10-20'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
