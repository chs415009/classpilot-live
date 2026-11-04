-- Stage 2, step 3: Cortex Search service over the approved chunks.
-- Run after scripts/load_chunks.py has filled LESSON_CHUNKS.
-- Cortex Search and its default embedding model run natively in <account region>.
-- https://docs.snowflake.com/en/sql-reference/sql/create-cortex-search

USE ROLE CLASSPILOT_AGENT_ROLE;
USE WAREHOUSE CLASSPILOT_WH;
USE SCHEMA CLASSPILOT_DEMO.AGENT;

-- Content is static, so a long target lag is fine (refresh cost stays near zero).
-- Default embedding model: snowflake-arctic-embed-m-v1.5.
CREATE OR REPLACE CORTEX SEARCH SERVICE LESSON_SEARCH
  ON CHUNK_TEXT
  ATTRIBUTES OBJECTIVE_ID, LESSON_ID
  WAREHOUSE = CLASSPILOT_WH
  TARGET_LAG = '1 day'
  AS SELECT CHUNK_ID, LESSON_ID, OBJECTIVE_ID, CHUNK_TEXT FROM LESSON_CHUNKS;

-- Manual check (Stage 2 "done" criterion): should return chunk-01 near the top.
SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
  'CLASSPILOT_DEMO.AGENT.LESSON_SEARCH',
  '{"query": "Why do we keep raw data in Bronze if it has errors?",
    "columns": ["CHUNK_ID", "OBJECTIVE_ID", "CHUNK_TEXT"],
    "limit": 3}'
);

-- Same query with an objective filter.
SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
  'CLASSPILOT_DEMO.AGENT.LESSON_SEARCH',
  '{"query": "what does ref() do",
    "columns": ["CHUNK_ID", "OBJECTIVE_ID"],
    "filter": {"@eq": {"OBJECTIVE_ID": "objective-03"}},
    "limit": 3}'
);
