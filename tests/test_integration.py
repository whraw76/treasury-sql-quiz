"""Real PostgreSQL checks; use a disposable seeded database, never an admin login."""

import os
from uuid import uuid4

import psycopg
import pytest

from app import create_app
from db import QueryRunner, QuizStore
from scripts.verify_live import verify
from tests.conftest import FakeAuth

pytestmark = pytest.mark.integration


@pytest.fixture
def database():
    reader = os.getenv("TEST_QUERY_DATABASE_URL")
    writer = os.getenv("TEST_SAVE_DATABASE_URL")
    if not reader or not writer:
        pytest.skip("Set TEST_QUERY_DATABASE_URL and TEST_SAVE_DATABASE_URL for a disposable database.")
    return reader, writer


@pytest.mark.parametrize("question_index", range(5))
def test_actual_postgres_matches_each_hint(database, quiz, question_index):
    question = quiz["questions"][question_index]
    assert QueryRunner(database[0]).run(question["reference_sql"]) == question["expected"]


def test_different_sql_same_result_and_empty_result(database):
    runner = QueryRunner(database[0])
    assert runner.run("SELECT COUNT(*) AS n FROM yields") == {
        "columns": ["n"], "rows": [[60]], "truncated": False,
    }
    assert runner.run("SELECT date FROM yields WHERE maturity_years = 99")["rows"] == []
    assert len(runner.run("SELECT * FROM yields a CROSS JOIN yields b")["rows"]) == 200
    assert runner.run("SELECT * FROM yields a CROSS JOIN yields b")["truncated"] is True


def test_reader_cannot_write_even_with_readonly_setting_disabled(database):
    # Exercise PostgreSQL GRANTs directly, bypassing the application's SQL parser.
    with psycopg.connect(database[0]) as conn:
        conn.execute("SET TRANSACTION READ WRITE")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM quiz_data.yields")


def test_reader_cannot_see_private_quizzes(database):
    with psycopg.connect(database[0]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM quiz_app.quizzes")


def test_save_reopen_update_and_other_owner_isolation(database, quiz):
    owner, other = str(uuid4()), str(uuid4())
    store = QuizStore(database[1])
    quiz["title"] = "Student's quiz'); DROP TABLE quiz_data.yields; --"
    quiz_id = store.save(owner, quiz)
    assert store.get(owner, quiz_id) == quiz
    assert store.list(owner)[0]["title"] == quiz["title"]
    assert store.get(other, quiz_id) is None
    assert store.list(other) == []
    with pytest.raises(PermissionError):
        store.save(other, quiz, quiz_id)
    quiz["title"] = "Updated quiz"
    assert store.save(owner, quiz, quiz_id) == quiz_id
    assert store.get(owner, quiz_id)["title"] == "Updated quiz"
    assert QueryRunner(database[0]).run("SELECT COUNT(*) FROM yields")["rows"] == [[60]]


def test_http_query_and_saved_quiz_use_postgres(database, quiz):
    # Auth is isolated here. Real Supabase sign-in still needs a deployed smoke test.
    application = create_app({
        "TESTING": True, "SECRET_KEY": "test-only-secret",
        "AUTH": FakeAuth(), "RUNNER": QueryRunner(database[0]), "STORE": QuizStore(database[1]),
    })
    client = application.test_client()
    headers = {"X-CSRF-Token": client.get("/api/bootstrap").json["csrf_token"]}
    assert client.post("/api/query", json={"sql": "SELECT * FROM yields"}, headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "valid-password"}, headers=headers).status_code == 200
    result = client.post("/api/query", json={"sql": quiz["questions"][0]["reference_sql"]}, headers=headers)
    assert result.json == quiz["questions"][0]["expected"]
    saved = client.post("/api/quizzes", json={"quiz": quiz}, headers=headers)
    assert saved.status_code == 201
    reopened = client.get("/api/quizzes/" + saved.json["id"])
    assert reopened.json["quiz"]["questions"][4]["expected"] == quiz["questions"][4]["expected"]


def test_live_verifier_checks_data_and_grants(database):
    verify(database[0], allow_local=True)
