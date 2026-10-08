CREATE EXTENSION IF NOT EXISTS vector;
-- Separate database for automated tests, so they never touch real data.
CREATE DATABASE kb_test;
\c kb_test
CREATE EXTENSION IF NOT EXISTS vector;
