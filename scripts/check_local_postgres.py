"""Optional development check using a disposable PostgreSQL server, not Supabase.

Install its test-only dependency with: python -m pip install pgserver==0.1.4
"""

import os
from pathlib import Path
import secrets
import sys
import tempfile

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.setup_database import initialize  # noqa: E402


def main():
    try:
        import pgserver
    except ImportError:
        print("Install the optional test runtime: python -m pip install pgserver==0.1.4")
        return 1
    server = pgserver.get_server(tempfile.mkdtemp(prefix="treasury-sql-pg-"), cleanup_mode="delete")
    try:
        admin_url = server.get_uri()
        passwords = {role: secrets.token_urlsafe(20) for role in ["treasury_reader", "treasury_writer"]}
        with psycopg.connect(admin_url) as conn:
            initialize(conn, passwords["treasury_reader"], passwords["treasury_writer"])
        params = conninfo_to_dict(admin_url)
        for variable, role in [
            ("TEST_QUERY_DATABASE_URL", "treasury_reader"),
            ("TEST_SAVE_DATABASE_URL", "treasury_writer"),
        ]:
            os.environ[variable] = make_conninfo(**dict(params, user=role, password=passwords[role]))
        os.chdir(ROOT)
        return pytest.main(["-q"])
    finally:
        server.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
