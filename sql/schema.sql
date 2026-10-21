-- Run after creating the two dedicated roles. No passwords belong in this file.
CREATE SCHEMA IF NOT EXISTS quiz_data;
CREATE SCHEMA IF NOT EXISTS quiz_app;
REVOKE ALL ON SCHEMA quiz_data, quiz_app FROM PUBLIC;

CREATE TABLE IF NOT EXISTS quiz_data.maturities (
    years integer PRIMARY KEY CHECK (years > 0),
    name text NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS quiz_data.yields (
    date date NOT NULL,
    maturity_years integer NOT NULL REFERENCES quiz_data.maturities(years),
    yield_percent numeric(7,4) NOT NULL,
    PRIMARY KEY (date, maturity_years)
);
CREATE TABLE IF NOT EXISTS quiz_app.quizzes (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    document jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(document) = 'object')
);
CREATE INDEX IF NOT EXISTS quizzes_owner_idx ON quiz_app.quizzes(owner_id);

REVOKE ALL ON ALL TABLES IN SCHEMA quiz_data, quiz_app FROM PUBLIC;
GRANT USAGE ON SCHEMA quiz_data TO treasury_reader;
GRANT SELECT ON quiz_data.maturities, quiz_data.yields TO treasury_reader;
GRANT USAGE ON SCHEMA quiz_app TO treasury_writer;
GRANT SELECT, INSERT, UPDATE ON quiz_app.quizzes TO treasury_writer;
ALTER ROLE treasury_reader SET default_transaction_read_only = on;
ALTER ROLE treasury_reader SET statement_timeout = '5s';
ALTER ROLE treasury_reader SET search_path = pg_catalog, quiz_data;
