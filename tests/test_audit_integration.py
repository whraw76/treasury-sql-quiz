import copy
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest

from audit_checks import verify_audit_permissions
from db import AuditLog, QuizStore, is_local_host
from scripts.verify_audit import verify

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def audit_database():
    urls = tuple(os.getenv(key) for key in (
        "TEST_QUERY_DATABASE_URL", "TEST_SAVE_DATABASE_URL", "TEST_ADMIN_DATABASE_URL"))
    if not all(urls):
        pytest.skip("Run scripts/check_local_postgres.py for disposable audit integration tests.")
    if not all(is_local_host(conninfo_to_dict(url).get("host", "")) for url in urls):
        pytest.fail("Audit integration tests require a local disposable database.")
    return urls


def test_query_text_and_actor_are_stored_as_data(audit_database):
    _, writer, admin = audit_database
    actor = str(uuid4())
    sql = "SELECT 'student''s note'; -- 收益率"
    AuditLog(writer).query(actor, sql, "success", {"returned_rows": 1, "truncated": False})
    with psycopg.connect(admin) as conn:
        row = conn.execute(
            "SELECT actor_id, sql_text, outcome, details, occurred_at FROM quiz_audit.events WHERE actor_id = %s",
            (actor,),
        ).fetchone()
    assert str(row[0]) == actor
    assert row[1:4] == (sql, "success", {"returned_rows": 1, "truncated": False})
    assert row[4].tzinfo is not None


def test_each_save_keeps_an_unchanged_snapshot(audit_database, quiz):
    _, writer, admin = audit_database
    actor = str(uuid4())
    store = QuizStore(writer)
    quiz["answers"] = ["SELECT 'O''Reilly';", "SELECT", "", "", ""]
    before = copy.deepcopy(quiz)
    quiz_id = store.save(actor, quiz)
    quiz["answers"][0] = "SELECT COUNT(*) FROM yields;"
    store.save(actor, quiz, quiz_id)
    with psycopg.connect(admin) as conn:
        events = conn.execute(
            "SELECT details, quiz_id FROM quiz_audit.events WHERE actor_id = %s ORDER BY occurred_at",
            (actor,),
        ).fetchall()
    assert len(events) == 2
    assert events[0][0] == {"quiz": before}
    assert events[1][0] == {"quiz": quiz}
    assert all(str(row[1]) == quiz_id for row in events)


def test_failed_audit_insert_rolls_back_quiz_save(audit_database, quiz):
    _, writer, admin = audit_database
    actor = str(uuid4())
    store = QuizStore(writer)
    quiz_id = store.save(actor, quiz)
    with psycopg.connect(admin) as conn:
        conn.execute("REVOKE INSERT (details) ON quiz_audit.events FROM treasury_writer")
    try:
        edited = copy.deepcopy(quiz)
        edited["title"] = "Must not be committed"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            store.save(actor, edited, quiz_id)
        assert store.get(actor, quiz_id) == quiz
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT count(*) FROM quiz_audit.events WHERE actor_id = %s", (actor,)).fetchone()[0] == 1
    finally:
        with psycopg.connect(admin) as conn:
            conn.execute("GRANT INSERT (details) ON quiz_audit.events TO treasury_writer")


def test_actual_audit_mutations_are_denied(audit_database):
    reader, writer, _ = audit_database
    verify(reader, writer)


@pytest.mark.parametrize("role_index", [0, 1])
def test_app_roles_cannot_read_audit_history(audit_database, role_index):
    with psycopg.connect(audit_database[role_index]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM quiz_audit.events")


def test_writer_cannot_supply_a_false_timestamp(audit_database):
    with psycopg.connect(audit_database[1]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                """INSERT INTO quiz_audit.events (id, actor_id, action, outcome, sql_text, details, occurred_at)
                   VALUES (%s, %s, 'query', 'success', 'SELECT 1', '{}', '2000-01-01')""",
                (uuid4(), uuid4()),
            )


def test_integrity_check_detects_accidental_update_grant(audit_database):
    reader, _, admin = audit_database
    with psycopg.connect(admin) as conn:
        conn.execute("GRANT UPDATE (details) ON quiz_audit.events TO treasury_writer")
    try:
        with psycopg.connect(reader) as conn:
            with pytest.raises(RuntimeError, match="must not read, edit or delete"):
                verify_audit_permissions(conn)
    finally:
        with psycopg.connect(admin) as conn:
            conn.execute("REVOKE UPDATE (details) ON quiz_audit.events FROM treasury_writer")


def test_migration_can_be_reapplied_without_losing_events(audit_database):
    reader, writer, admin = audit_database
    actor = str(uuid4())
    AuditLog(writer).query(actor, "SELECT 1", "success", {"returned_rows": 1})
    with psycopg.connect(admin) as conn:
        conn.execute((ROOT / "sql/audit_log.sql").read_text(), prepare=False)
        assert conn.execute("SELECT count(*) FROM quiz_audit.events WHERE actor_id = %s", (actor,)).fetchone()[0] == 1
    with psycopg.connect(reader) as conn:
        verify_audit_permissions(conn)
