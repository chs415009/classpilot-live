-- Cost reading for a live step. Read-only (SELECT on ACCOUNT_USAGE). Run in Snowsight as
-- ACCOUNTADMIN, or any role that can read SNOWFLAKE.ACCOUNT_USAGE (the service user
-- cannot, Stage 12 finding). ACCOUNT_USAGE lags behind real time, so run it a few hours
-- after the step. Set the window below to the step's whole UTC hours: START_TIME is the
-- start of an hourly bucket, so a bound inside an hour drops that hour (Stage 7 finding).
-- Replaces the per-stage files of Stages 1-9 (their readings are in docs/agent/note.md).

USE ROLE ACCOUNTADMIN;

-- 1. AI function credits per function and model.
SELECT FUNCTION_NAME,
       MODEL_NAME,
       COUNT(DISTINCT QUERY_ID)            AS queries,
       ROUND(SUM(CREDITS), 4)              AS ai_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
WHERE START_TIME >= '<START, e.g. 2026-11-06 04:00:00 +00:00>'
  AND START_TIME <  '<END, e.g. 2026-11-06 08:00:00 +00:00>'
GROUP BY 1, 2
ORDER BY 1, 2;

-- 2. Warehouse credits per hour (AI_COMPLETE keeps the warehouse up while it runs).
SELECT WAREHOUSE_NAME, START_TIME, ROUND(CREDITS_USED, 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE START_TIME >= '<START, e.g. 2026-11-06 04:00:00 +00:00>'
  AND START_TIME <  '<END, e.g. 2026-11-06 08:00:00 +00:00>'
ORDER BY 1, 2;

-- 3. Cortex Search credits for the day (daily rows).
SELECT USAGE_DATE, SERVICE_NAME, CONSUMPTION_TYPE, ROUND(SUM(CREDITS), 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
WHERE USAGE_DATE = '<DATE, e.g. 2026-11-06>'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
