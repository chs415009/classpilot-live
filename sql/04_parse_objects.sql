-- Stage 5: parse-layer objects (IMPLEMENTATION_NOTES 4.4, interface_questions Q-17).
-- Template: placeholders in double braces are filled by scripts/run_sql.py from .env (ROLE,
-- WAREHOUSE, DATABASE, SCHEMA) and config/settings.yaml `objects`. The script prints
-- the rendered SQL and runs it only with --execute. Rerunnable (IF NOT EXISTS).
-- Needs CREATE STAGE and CREATE TABLE on the schema (granted in sql/01 and Stage 1).
-- https://docs.snowflake.com/en/sql-reference/sql/create-stage

USE ROLE {{ROLE}};
USE WAREHOUSE {{WAREHOUSE}};
USE SCHEMA {{DATABASE}}.{{SCHEMA}};

-- Bronze: uploaded files and the PNGs of pages that go to vision. SNOWFLAKE_SSE is
-- required for AI_COMPLETE image input and cannot be changed later (Stage 1). The
-- directory table is refreshed after each PUT batch.
CREATE STAGE IF NOT EXISTS {{RAW_STAGE}}
  DIRECTORY = (ENABLE = TRUE)
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'ClassPilot prep: uploaded materials and page images';

-- Bronze: one row per file per lesson. FILE_ID = SHA256 of the file bytes.
CREATE TABLE IF NOT EXISTS {{RAW_FILES}} (
  LESSON_ID     STRING NOT NULL,
  FILE_ID       STRING NOT NULL,
  SOURCE_ID     STRING NOT NULL,
  KIND          STRING NOT NULL,   -- slides | reference
  FORMAT        STRING NOT NULL,   -- pptx | pdf | docx
  ORIGINAL_NAME STRING,
  SHA256        STRING NOT NULL,
  STAGE_PATH    STRING NOT NULL,
  PAGE_COUNT    NUMBER,
  UPLOADED_AT   TIMESTAMP_TZ NOT NULL,
  PRIMARY KEY (LESSON_ID, FILE_ID)
);

-- Silver: one row per page of a file, independent of lessons (a known hash is never
-- parsed again). PARSE_METHOD: local_text | ai_parse_layout | vision | vision_failed.
CREATE TABLE IF NOT EXISTS {{PARSED_PAGES}} (
  FILE_ID         STRING NOT NULL,
  PAGE_INDEX      NUMBER NOT NULL,  -- 1-based
  PAGE_ID         STRING NOT NULL,  -- <source>-p<NN>
  TEXT_LAYER      STRING,
  NOTES           STRING,
  LLM_DESCRIPTION VARIANT,          -- slide_text, diagram_description, key_concepts
  IMAGE_FLAG      STRING,           -- image | text | unsure
  PARSE_METHOD    STRING NOT NULL,
  PARSED_AT       TIMESTAMP_TZ NOT NULL,
  PRIMARY KEY (FILE_ID, PAGE_INDEX)
);

-- Gold: search chunks, copied per lesson. Change tracking feeds the search service.
CREATE TABLE IF NOT EXISTS {{CHUNKS}} (
  LESSON_ID  STRING NOT NULL,
  CHUNK_ID   STRING NOT NULL,  -- <source>-p<NN>-c<n>
  FILE_ID    STRING NOT NULL,
  SOURCE_ID  STRING NOT NULL,
  PAGE_ID    STRING NOT NULL,
  PAGE_INDEX NUMBER NOT NULL,
  ORIGIN     STRING NOT NULL,  -- text_layer | llm_description
  CHUNK_TEXT STRING NOT NULL,
  LOADED_AT  TIMESTAMP_TZ NOT NULL,
  PRIMARY KEY (LESSON_ID, CHUNK_ID)
)
CHANGE_TRACKING = TRUE;
