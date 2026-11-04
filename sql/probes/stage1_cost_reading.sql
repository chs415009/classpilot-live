-- Stage 1 cost reading. Read-only (SELECT on ACCOUNT_USAGE). Run in Snowsight as
-- ACCOUNTADMIN, or any role that can read SNOWFLAKE.ACCOUNT_USAGE.
-- CORTEX_FUNCTIONS_QUERY_USAGE_HISTORY is no longer updated (docs, 2026-11-04); use the
-- view below. Its CREDITS column excludes warehouse credits. Latency about 5 minutes.
-- WAREHOUSE_METERING_HISTORY lags up to 3 hours.
-- https://docs.snowflake.com/en/sql-reference/account-usage/cortex_ai_functions_usage_history

USE ROLE ACCOUNTADMIN;

-- 1. AI function usage per day, function, and model since the account was set up
--    (v1 Stages 2-4 calibration, then this stage).
SELECT DATE_TRUNC('day', START_TIME)       AS day,
       FUNCTION_NAME,
       MODEL_NAME,
       COUNT(DISTINCT QUERY_ID)            AS queries,
       ROUND(SUM(CREDITS), 4)              AS ai_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
WHERE START_TIME >= '2026-10-20'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

-- 2. Token metrics per query for the last day (to get cost per call).
SELECT START_TIME, FUNCTION_NAME, MODEL_NAME, QUERY_ID, METRICS, CREDITS
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
WHERE START_TIME >= DATEADD('day', -1, CURRENT_TIMESTAMP())
ORDER BY START_TIME;

-- 3. Warehouse credits per day.
SELECT DATE_TRUNC('day', START_TIME) AS day, WAREHOUSE_NAME,
       ROUND(SUM(CREDITS_USED), 4)   AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE START_TIME >= '2026-10-20'
GROUP BY 1, 2
ORDER BY 1, 2;
