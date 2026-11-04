-- Stage 2, step 2: table for the approved lesson chunks.
-- Only static, approved content goes here. Rows are loaded from
-- content/lesson_chunks.json by scripts/load_chunks.py (single source of truth).

USE ROLE CLASSPILOT_AGENT_ROLE;
USE WAREHOUSE CLASSPILOT_WH;
USE SCHEMA CLASSPILOT_DEMO.AGENT;

CREATE TABLE IF NOT EXISTS LESSON_CHUNKS (
  CHUNK_ID     STRING NOT NULL,
  LESSON_ID    STRING NOT NULL,
  OBJECTIVE_ID STRING NOT NULL,
  CHUNK_TEXT   STRING NOT NULL
);

-- Cortex Search needs change tracking on the source table.
ALTER TABLE LESSON_CHUNKS SET CHANGE_TRACKING = TRUE;
