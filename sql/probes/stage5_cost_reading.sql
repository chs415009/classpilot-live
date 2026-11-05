-- Stage 5 cost reading. Read-only (SELECT on ACCOUNT_USAGE). Run in Snowsight as
-- ACCOUNTADMIN, or any role that can read SNOWFLAKE.ACCOUNT_USAGE. ACCOUNT_USAGE lags
-- (up to about 3 hours), so run it a few hours after the live run.
-- Stage 5 live run (2026-11-05): 1 AI_PARSE_DOCUMENT (3 pages), 7 vision AI_COMPLETE
-- (claude-haiku-4-5), LESSON_SEARCH_V2 created over 57 chunk rows (3 lessons), 4
-- queries, then suspended.

USE ROLE ACCOUNTADMIN;

-- 1. AI function credits for the day, per function and model.
SELECT FUNCTION_NAME,
       MODEL_NAME,
       COUNT(DISTINCT QUERY_ID)            AS queries,
       ROUND(SUM(CREDITS), 4)              AS ai_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
WHERE START_TIME >= '2026-11-05'
GROUP BY 1, 2
ORDER BY 1, 2;

-- 2. Warehouse credits for the day.
SELECT WAREHOUSE_NAME, ROUND(SUM(CREDITS_USED), 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE START_TIME >= '2026-11-05'
GROUP BY 1
ORDER BY 1;

-- 3. Cortex Search credits for the day (SERVING / EMBED_TEXT_TOKENS / BATCH).
SELECT USAGE_DATE, SERVICE_NAME, CONSUMPTION_TYPE, ROUND(SUM(CREDITS), 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
WHERE USAGE_DATE >= '2026-11-05'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
