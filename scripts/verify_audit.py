"""Check audit permissions using the app's existing reader and writer logins."""

import os
from pathlib import Path
import sys

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audit_checks import verify_audit_permissions  # noqa: E402
from db import validate_database_url  # noqa: E402


def verify(reader_url, writer_url):
    for role, url in (("treasury_reader", reader_url), ("treasury_writer", writer_url)):
        validate_database_url(url, role)
        with psycopg.connect(url, connect_timeout=8) as conn:
            verify_audit_permissions(conn)
            conn.rollback()
            for statement in (
                "UPDATE quiz_audit.events SET outcome = 'failed' WHERE false",
                "DELETE FROM quiz_audit.events WHERE false",
                "TRUNCATE quiz_audit.events",
            ):
                # Roll back even if a permission was accidentally granted.
                try:
                    conn.execute("SET TRANSACTION READ WRITE")
                    conn.execute("SET LOCAL statement_timeout = '5s'")
                    conn.execute(statement)
                except psycopg.errors.InsufficientPrivilege:
                    pass
                else:
                    raise RuntimeError(f"{role} unexpectedly changed the audit table.")
                finally:
                    conn.rollback()
        print(f"PASS: {role} cannot UPDATE, DELETE or TRUNCATE audit events.")


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    try:
        verify(os.getenv("QUERY_DATABASE_URL", ""), os.getenv("SAVE_DATABASE_URL", ""))
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}. Check the audit migration and permissions.", file=sys.stderr)
        raise SystemExit(1) from None
