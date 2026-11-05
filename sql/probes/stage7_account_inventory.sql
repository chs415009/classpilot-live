-- Stage 7 pre-run inventory: what is left in the account from v1 and earlier stages.
-- Read-only (SHOW, DESC, SELECT); nothing is created, changed, or dropped. Run in
-- Snowsight as ACCOUNTADMIN (the agent's service role cannot see users or grants).
-- Only section 4 needs a warehouse (seconds on CLASSPILOT_WH, XSMALL).
-- Object names are the defaults from sql/01 and config/settings.yaml `objects`.

USE ROLE ACCOUNTADMIN;

-- 1. The agent's objects. Expected (v2): RAW_FILES, PARSED_PAGES, LESSON_CHUNKS_V2,
--    stage RAW_MATERIALS, search service LESSON_SEARCH_V2. Left from v1: LESSON_CHUNKS,
--    LESSON_SEARCH. PROBE_STAGE was dropped in Stage 1 and should not be listed.
SHOW WAREHOUSES LIKE 'CLASSPILOT%';
SHOW SCHEMAS IN DATABASE CLASSPILOT_DEMO;
SHOW OBJECTS IN DATABASE CLASSPILOT_DEMO;                       -- every table/view, all schemas
SHOW STAGES IN SCHEMA CLASSPILOT_DEMO.AGENT;
SHOW CORTEX SEARCH SERVICES IN SCHEMA CLASSPILOT_DEMO.AGENT;   -- serving_state, indexing_state
SHOW TASKS IN DATABASE CLASSPILOT_DEMO;                         -- expected: none

-- 2. Identities. Expected: CLASSPILOT_AGENT_SVC (TYPE = SERVICE) with one RSA key, and
--    your login user. A second key fingerprint (RSA_PUBLIC_KEY_2_FP) would be a v1 leftover.
SHOW USERS LIKE 'CLASSPILOT%';
DESC USER CLASSPILOT_AGENT_SVC;
SHOW NETWORK POLICIES;                                          -- expected: none (Route A unused)

-- 3. Roles and grants. Expected on CLASSPILOT_AGENT_ROLE: USAGE on CLASSPILOT_WH and
--    CLASSPILOT_DEMO; USAGE, CREATE TABLE, CREATE STAGE, CREATE CORTEX SEARCH SERVICE on
--    the schema; SNOWFLAKE.CORTEX_USER; ownership of the objects it created; OPERATE on
--    the search services. Holders: CLASSPILOT_AGENT_SVC and your login user.
SHOW ROLES LIKE 'CLASSPILOT%';
SHOW GRANTS TO ROLE CLASSPILOT_AGENT_ROLE;
SHOW GRANTS OF ROLE CLASSPILOT_AGENT_ROLE;
SHOW GRANTS TO USER CLASSPILOT_AGENT_SVC;

-- 4. Lessons in the v2 tables (Stage 5 created 57 chunk rows over 3 lessons).
USE WAREHOUSE CLASSPILOT_WH;
SELECT LESSON_ID, COUNT(*) AS chunks
FROM CLASSPILOT_DEMO.AGENT.LESSON_CHUNKS_V2 GROUP BY 1 ORDER BY 1;
SELECT LESSON_ID, COUNT(*) AS files, MIN(UPLOADED_AT) AS first_upload
FROM CLASSPILOT_DEMO.AGENT.RAW_FILES GROUP BY 1 ORDER BY 1;
SELECT COUNT(DISTINCT FILE_ID) AS files, COUNT(*) AS pages
FROM CLASSPILOT_DEMO.AGENT.PARSED_PAGES;
