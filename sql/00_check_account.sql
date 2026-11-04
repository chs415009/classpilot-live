-- Stage 2, step 0: check the account before creating anything.
-- Run in a Snowsight worksheet as ACCOUNTADMIN, one statement at a time.
--
-- Before this: trial accounts have AI features disabled by default. Add a credit card
-- in Snowsight (Admin -> Billing) to enable them. This does not end the trial; usage
-- still comes out of trial credits.
-- https://docs.snowflake.com/en/user-guide/admin-trial-account

USE ROLE ACCOUNTADMIN;

-- Queries need a running warehouse. Create the demo warehouse first (same definition
-- as 01_setup_objects.sql, which then skips it via IF NOT EXISTS).
CREATE WAREHOUSE IF NOT EXISTS CLASSPILOT_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;
USE WAREHOUSE CLASSPILOT_WH;
SELECT CURRENT_WAREHOUSE();

-- Expect <ACCOUNT_REGION>. Note the account identifier (orgname-accountname) for .env.
SELECT CURRENT_REGION(), CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME() AS account_identifier;

-- No AI_COMPLETE model runs natively in <account region>, so LLM calls need
-- cross-region inference. Check the current value first.
-- https://docs.snowflake.com/en/user-guide/snowflake-cortex/cross-region-inference
SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;

-- Only if the value above is DISABLED: allow processing in AWS US regions.
-- Data-residency note: prompts (lesson text + student questions) are then processed
-- in the US. Agree with the team before running this.
-- ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'AWS_US';

-- Trivial LLM check. If this returns text, Cortex LLM access works.
-- Try a few models to see which ones the account can reach.
SELECT AI_COMPLETE('llama3.3-70b', 'Reply with the single word: ok');
SELECT AI_COMPLETE('mistral-large3', 'Reply with the single word: ok');
SELECT AI_COMPLETE('claude-haiku-4-5', 'Reply with the single word: ok');
