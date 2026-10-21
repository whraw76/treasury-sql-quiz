"""One-time setup for a NEW Supabase quiz database. Admin credentials stay local."""

import csv
import getpass
import json
import os
from pathlib import Path
import secrets
import sys

import psycopg
from dotenv import dotenv_values
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]


def initialize(conn, reader_password, writer_password):
    for role, password in [("treasury_reader", reader_password), ("treasury_writer", writer_password)]:
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
            raise RuntimeError(f"Role {role} already exists. Setup stopped without resetting it.")
        conn.execute(sql.SQL(
            "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5"
        ).format(sql.Identifier(role), sql.Literal(password)))
    conn.execute((ROOT / "sql/schema.sql").read_text(), prepare=False)
    conn.execute((ROOT / "sql/audit_log.sql").read_text(), prepare=False)
    conn.cursor().executemany(
        "INSERT INTO quiz_data.maturities(years, name) VALUES (%s, %s)",
        [(2, "2-year"), (10, "10-year"), (30, "30-year")],
    )
    with (ROOT / "data/treasury_sample.csv").open() as file:
        rows = list(csv.DictReader(file))
    conn.cursor().executemany(
        "INSERT INTO quiz_data.yields(date, maturity_years, yield_percent) VALUES (%s, %s, %s)",
        [(r["date"], r["maturity_years"], r["yield_percent"]) for r in rows],
    )


def main():
    env_path = ROOT / ".env"
    configuration = dotenv_values(env_path) if env_path.exists() else {}
    existing_url = configuration.get("QUERY_DATABASE_URL", "")
    if existing_url and "PROJECT_REF" not in existing_url and "PASSWORD" not in existing_url:
        raise RuntimeError("A configured .env already exists. Setup will not overwrite it.")
    if configuration.get("SUPABASE_POOLER_HOST") and configuration.get("SUPABASE_PROJECT_REF"):
        params = {
            "host": configuration["SUPABASE_POOLER_HOST"], "port": "5432", "dbname": "postgres",
            "user": "postgres." + configuration["SUPABASE_PROJECT_REF"],
        }
    else:
        admin_url = getpass.getpass("Supabase Session pooler admin connection string (hidden): ")
        params = conninfo_to_dict(admin_url)
    if not params.get("host", "").endswith(".pooler.supabase.com") or params.get("port", "5432") != "5432":
        raise RuntimeError("Copy the Session pooler connection string on port 5432.")
    if not params.get("user", "").startswith("postgres."):
        raise RuntimeError("Use the initial postgres.PROJECT_REF login for setup only.")
    params["sslmode"] = "require"
    project_ref = params["user"].split(".", 1)[1]
    if not params.get("password"):
        print(f"Setting up project {project_ref} through its Session pooler with SSL.")
        params["password"] = getpass.getpass("Database password (hidden): ")
        if not params["password"]:
            raise RuntimeError("Enter the password you set when creating the Supabase project.")
    supabase_url = configuration.get("SUPABASE_URL", "")
    if not supabase_url or "YOUR_PROJECT" in supabase_url:
        supabase_url = input(f"Supabase project URL [https://{project_ref}.supabase.co]: ").strip()
    supabase_url = supabase_url or f"https://{project_ref}.supabase.co"
    if not supabase_url.startswith("https://"):
        raise RuntimeError("Use the HTTPS Supabase project URL.")
    public_key = configuration.get("SUPABASE_KEY", "")
    if not public_key:
        public_key = getpass.getpass("Supabase publishable key (or legacy anon key; hidden): ").strip()
    if not public_key:
        raise RuntimeError("A Supabase publishable/anon key is required.")
    reader_password, writer_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with psycopg.connect(make_conninfo(**params), connect_timeout=10) as conn:
        initialize(conn, reader_password, writer_password)
    values = {
        "APP_ENV": "development", "SECRET_KEY": secrets.token_hex(32),
        "SUPABASE_URL": supabase_url,
        "SUPABASE_KEY": public_key,
    }
    for variable, role, password in [
        ("QUERY_DATABASE_URL", "treasury_reader", reader_password),
        ("SAVE_DATABASE_URL", "treasury_writer", writer_password),
    ]:
        role_params = dict(params, user=f"{role}.{project_ref}", password=password)
        values[variable] = make_conninfo(**role_params)
    contents = "# Local credentials. Never commit or share this file.\n"
    contents += "\n".join(f"{key}={json.dumps(value)}" for key, value in values.items()) + "\n"
    descriptor = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(contents)
    os.chmod(env_path, 0o600)
    print("Created two restricted roles, four tables and 60 yield records.")
    print("Saved app credentials to ignored .env (owner-readable only). Admin credentials were not saved.")
    print("Next: python scripts/verify_live.py")


if __name__ == "__main__":
    try:
        main()
    except (psycopg.Error, RuntimeError) as exc:
        # Database exceptions can contain host/connection details; keep those out of logs.
        print(str(exc) if isinstance(exc, RuntimeError) else "Database setup failed. Check the connection and permissions.", file=sys.stderr)
        raise SystemExit(1) from None
