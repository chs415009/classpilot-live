-- Stage 9 cost reading. Read-only (SELECT on ACCOUNT_USAGE). Run in Snowsight as
-- ACCOUNTADMIN, or any role that can read SNOWFLAKE.ACCOUNT_USAGE. ACCOUNT_USAGE lags
-- behind real time, so run it a few hours after the last live step.
-- Stage 9 live steps (2026-11-06, 04:53-07:25 UTC), all mistral-large3 unless noted:
-- dev baseline and compiled dev evals, Guardian case evals (one with claude-haiku-4-5,
-- one with claude-sonnet-4-5), five prep compiles, two live compiles, four L1 prep runs
-- (LESSON_SEARCH_V2 resumed and suspended around each), about 780 LLM calls in all.
-- START_TIME is the start of an hourly bucket, so the bounds are whole hours
-- (04:00 to 08:00 UTC); a bound inside an hour drops that hour (Stage 7 finding).

USE ROLE ACCOUNTADMIN;

-- 1. AI function credits per function and model.
SELECT FUNCTION_NAME,
       MODEL_NAME,
       COUNT(DISTINCT QUERY_ID)            AS queries,
       ROUND(SUM(CREDITS), 4)              AS ai_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
WHERE START_TIME >= '2026-11-06 04:00:00 +00:00'
  AND START_TIME <  '2026-11-06 08:00:00 +00:00'
GROUP BY 1, 2
ORDER BY 1, 2;

-- 2. Warehouse credits per hour (AI_COMPLETE keeps the warehouse up while it runs).
SELECT WAREHOUSE_NAME, START_TIME, ROUND(CREDITS_USED, 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE START_TIME >= '2026-11-06 04:00:00 +00:00'
  AND START_TIME <  '2026-11-06 08:00:00 +00:00'
ORDER BY 1, 2;

-- 3. Cortex Search credits for the day (daily rows).
SELECT USAGE_DATE, SERVICE_NAME, CONSUMPTION_TYPE, ROUND(SUM(CREDITS), 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
WHERE USAGE_DATE = '2026-11-06'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
