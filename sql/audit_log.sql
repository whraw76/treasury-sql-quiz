-- Apply as the database owner. Existing quizzes and yields are unchanged.
CREATE SCHEMA IF NOT EXISTS quiz_audit;
REVOKE ALL ON SCHEMA quiz_audit FROM PUBLIC, treasury_reader, treasury_writer;
GRANT USAGE ON SCHEMA quiz_audit TO treasury_writer;

CREATE TABLE IF NOT EXISTS quiz_audit.events (
    id uuid PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_id uuid NOT NULL,
    action text NOT NULL CHECK (action IN ('query', 'save')),
    outcome text NOT NULL CHECK (outcome IN ('success', 'rejected', 'failed')),
    sql_text text,
    quiz_id uuid,
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
    CHECK (
        (action = 'query' AND sql_text IS NOT NULL AND length(sql_text) <= 8000 AND quiz_id IS NULL)
        OR (action = 'save' AND quiz_id IS NOT NULL AND sql_text IS NULL AND outcome = 'success')
    )
);
CREATE INDEX IF NOT EXISTS audit_events_time_idx ON quiz_audit.events(occurred_at);
ALTER TABLE quiz_audit.events ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'quiz_audit'
        AND tablename = 'events' AND policyname = 'audit_append'
    ) THEN
        CREATE POLICY audit_append ON quiz_audit.events
            FOR INSERT TO treasury_writer WITH CHECK (true);
    END IF;
END $$;

-- The application may append events, but cannot read or change history.
REVOKE ALL ON quiz_audit.events FROM PUBLIC, treasury_reader, treasury_writer;
REVOKE ALL (id, occurred_at, actor_id, action, outcome, sql_text, quiz_id, details)
    ON quiz_audit.events FROM PUBLIC, treasury_reader, treasury_writer;
GRANT INSERT (id, actor_id, action, outcome, sql_text, quiz_id, details)
    ON quiz_audit.events TO treasury_writer;
