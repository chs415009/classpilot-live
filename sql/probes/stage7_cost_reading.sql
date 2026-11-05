-- Stage 7 cost reading. Read-only (SELECT on ACCOUNT_USAGE). Run in Snowsight as
-- ACCOUNTADMIN, or any role that can read SNOWFLAKE.ACCOUNT_USAGE. ACCOUNT_USAGE lags
-- behind real time, so run it a few hours after the live run.
-- Stage 7 live run (2026-11-05, from 20:50 UTC): LESSON_SEARCH_V2 resumed, two lessons
-- re-chunked (0 LLM calls), one `prep generate --backend cortex` on info6205-l1
-- (mistral-large3), then the service suspended. Stage 5 ran earlier the same day, so
-- the AI and warehouse readings are bounded by time, not by date.

USE ROLE ACCOUNTADMIN;

-- 1. AI function credits since the run started, per function and model. START_TIME is
--    the start of an hourly bucket, so the bound is the hour (20:00 UTC; Stage 5 ran in
--    the 19:00 hour, the inventory made no AI calls). With 20:50 only run 2 was counted.
SELECT FUNCTION_NAME,
       MODEL_NAME,
       COUNT(DISTINCT QUERY_ID)            AS queries,
       ROUND(SUM(CREDITS), 4)              AS ai_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
WHERE START_TIME >= '2026-11-05 20:00:00 +00:00'
GROUP BY 1, 2
ORDER BY 1, 2;

-- 2. Warehouse credits since the run started (hourly rows: the 20:00 UTC hour also
--    holds anything that ran on the warehouse before 20:50).
SELECT WAREHOUSE_NAME, START_TIME, ROUND(CREDITS_USED, 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE START_TIME >= '2026-11-05 20:00:00 +00:00'
ORDER BY 1, 2;

-- 3. Cortex Search credits for the day (daily rows; Stage 5 is in the same day).
SELECT USAGE_DATE, SERVICE_NAME, CONSUMPTION_TYPE, ROUND(SUM(CREDITS), 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
WHERE USAGE_DATE >= '2026-11-05'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
