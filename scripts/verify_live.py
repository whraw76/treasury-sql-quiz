"""Read-only live checks. Missing Secrets or an unreachable database MUST fail."""

import argparse
import json
import os
from pathlib import Path
import sys

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import QueryRunner, is_local_host, validate_database_url  # noqa: E402


def verify(url, allow_local=False):
    params = validate_database_url(url, "treasury_reader")
    if not allow_local and is_local_host(params.get("host", "")):
        raise RuntimeError("This check requires the hosted database, not a local substitute.")
    with psycopg.connect(url, connect_timeout=8) as conn:
        role = conn.execute(
            "SELECT current_user, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if role != ("treasury_reader", False, False, False, False):
            raise RuntimeError("The query login is not the expected restricted role.")
        can_write = conn.execute(
            "SELECT has_table_privilege(current_user, 'quiz_data.yields', 'INSERT,UPDATE,DELETE,TRUNCATE')"
        ).fetchone()[0]
        if can_write:
            raise RuntimeError("The query role must not modify the yield dataset.")
        if conn.execute("SELECT has_schema_privilege(current_user, 'quiz_app', 'USAGE')").fetchone()[0]:
            raise RuntimeError("The query role must not access private saved quizzes.")
        count = conn.execute("SELECT COUNT(*) FROM quiz_data.yields").fetchone()[0]
        if count != 60:
            raise RuntimeError(f"Expected 60 yield records, found {count}.")
    quiz = json.loads((ROOT / "data/quiz.json").read_text())
    if sum(q["points"] for q in quiz["questions"]) != 20:
        raise RuntimeError("The quiz must total 20 points.")
    runner = QueryRunner(url)
    for q in quiz["questions"]:
        actual = runner.run(q["reference_sql"])
        if actual != q["expected"]:
            raise RuntimeError(f"Question {q['id']}: live result does not match the documented hint.")
        print(f"Question {q['id']}: expected columns and {len(actual['rows'])} rows match PostgreSQL.")
    target = "LOCAL DEVELOPMENT DATABASE" if allow_local else "HOSTED DATABASE"
    print(f"PASS: {target}, restricted role, 60 records, and all five reference results.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-local", action="store_true", help="Development-only test; not evidence of hosted completion.")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    try:
        verify(os.getenv("QUERY_DATABASE_URL", ""), args.allow_local)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}. Verify the Secret, Session pooler, SSL, seed data and permissions.", file=sys.stderr)
        raise SystemExit(1) from None
