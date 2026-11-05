-- Stage 5: v2 Cortex Search service over the lesson chunks (one service, many lessons).
-- Template rendered by scripts/run_sql.py (see sql/04). Run once, after the first chunks
-- are loaded; prep then runs ALTER CORTEX SEARCH SERVICE ... REFRESH after each load
-- (Stage 1), so a long target lag is enough. Every query filters on LESSON_ID.
-- PRIMARY KEY columns must be TEXT.
-- https://docs.snowflake.com/en/sql-reference/sql/create-cortex-search

USE ROLE {{ROLE}};
USE WAREHOUSE {{WAREHOUSE}};
USE SCHEMA {{DATABASE}}.{{SCHEMA}};

CREATE CORTEX SEARCH SERVICE IF NOT EXISTS {{SEARCH_SERVICE}}
  ON CHUNK_TEXT
  PRIMARY KEY (LESSON_ID, CHUNK_ID)
  ATTRIBUTES LESSON_ID, SOURCE_ID
  WAREHOUSE = {{WAREHOUSE}}
  TARGET_LAG = '1 day'
  AS SELECT LESSON_ID, CHUNK_ID, SOURCE_ID, PAGE_ID, ORIGIN, CHUNK_TEXT FROM {{CHUNKS}};
