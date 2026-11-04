-- Stage 1 probe setup. Review first; then run in Snowsight, one statement at a time.
-- Object names are the configurable defaults from sql/01_setup_objects.sql.
-- Docs (checked 2026-11-04):
--   https://docs.snowflake.com/en/sql-reference/sql/create-stage
--   https://docs.snowflake.com/en/sql-reference/functions/ai_complete-single-file

-- Part 1 (ACCOUNTADMIN): let the agent role create stages in the demo schema.
-- The role was granted CREATE TABLE and CREATE CORTEX SEARCH SERVICE in v1, not CREATE STAGE.
-- Stage 5 needs the same grant for @RAW_MATERIALS.
USE ROLE ACCOUNTADMIN;
GRANT CREATE STAGE ON SCHEMA CLASSPILOT_DEMO.AGENT TO ROLE CLASSPILOT_AGENT_ROLE;

-- Part 2 (agent role): the probe stage.
-- SNOWFLAKE_SSE is required for AI_COMPLETE image input (client-side encrypted stages are
-- not supported) and cannot be changed after creation. The directory table lets us list
-- files; internal stages need ALTER STAGE ... REFRESH after PUT.
USE ROLE CLASSPILOT_AGENT_ROLE;
USE WAREHOUSE CLASSPILOT_WH;
USE SCHEMA CLASSPILOT_DEMO.AGENT;
CREATE STAGE IF NOT EXISTS PROBE_STAGE
  DIRECTORY = (ENABLE = TRUE)
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'Stage 1 probes only; dropped at the end of Stage 1';

-- After the probe script has PUT the files (it runs this itself):
-- ALTER STAGE PROBE_STAGE REFRESH;

-- Teardown at the end of Stage 1 (shown again before it runs):
-- REMOVE @PROBE_STAGE;
-- DROP STAGE IF EXISTS PROBE_STAGE;
