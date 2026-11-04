-- Stage 2, step 1: role, warehouse, database, schema, and a service user for Python.
-- Run in Snowsight as ACCOUNTADMIN.
--
-- Auth: key pair on a TYPE=SERVICE user. Password logins are being phased out for
-- programmatic users (MFA rollout), and PATs need a network policy.
-- https://docs.snowflake.com/en/user-guide/key-pair-auth

USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS CLASSPILOT_AGENT_ROLE;

CREATE WAREHOUSE IF NOT EXISTS CLASSPILOT_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS CLASSPILOT_DEMO;
CREATE SCHEMA IF NOT EXISTS CLASSPILOT_DEMO.AGENT;

GRANT USAGE ON WAREHOUSE CLASSPILOT_WH TO ROLE CLASSPILOT_AGENT_ROLE;
GRANT USAGE ON DATABASE CLASSPILOT_DEMO TO ROLE CLASSPILOT_AGENT_ROLE;
GRANT USAGE, CREATE TABLE, CREATE CORTEX SEARCH SERVICE
  ON SCHEMA CLASSPILOT_DEMO.AGENT TO ROLE CLASSPILOT_AGENT_ROLE;

-- Cortex LLM + search access. CORTEX_USER is granted to PUBLIC by default on new
-- accounts; granting it explicitly keeps working if that default is revoked.
-- https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql-privileges-and-access
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE CLASSPILOT_AGENT_ROLE;

-- Let your own login use the role too (for running 02/03 in Snowsight).
-- Replace <YOUR_USER> with the name shown by SELECT CURRENT_USER(); keep the double
-- quotes and the exact case (needed when the name has a dot, e.g. "first.last123").
GRANT ROLE CLASSPILOT_AGENT_ROLE TO USER "<YOUR_USER>";

-- Service user for the Python code. Paste the public key from rsa_key.pub without the
-- BEGIN/END lines (see README "Snowflake setup" for the openssl commands).
CREATE USER IF NOT EXISTS CLASSPILOT_AGENT_SVC
  TYPE = SERVICE
  DEFAULT_ROLE = CLASSPILOT_AGENT_ROLE
  DEFAULT_WAREHOUSE = CLASSPILOT_WH
  DEFAULT_NAMESPACE = CLASSPILOT_DEMO.AGENT;
ALTER USER CLASSPILOT_AGENT_SVC SET RSA_PUBLIC_KEY = '<PASTE_PUBLIC_KEY_HERE>';
GRANT ROLE CLASSPILOT_AGENT_ROLE TO USER CLASSPILOT_AGENT_SVC;

-- Check: RSA_PUBLIC_KEY_FP should be set.
DESC USER CLASSPILOT_AGENT_SVC;
