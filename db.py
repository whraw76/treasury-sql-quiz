"""Two separate database logins: dataset SELECTs and owner-scoped quiz saves."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from query_policy import MAX_ROWS, QueryError, prepare_query


class ConfigurationError(RuntimeError):
    pass


def is_local_host(host):
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("/")


def validate_database_url(url, expected_role):
    if not url or "PASSWORD" in url or "PROJECT_REF" in url:
        raise ConfigurationError("Database setup is not complete yet.")
    try:
        params = conninfo_to_dict(url)
    except psycopg.Error as exc:
        raise ConfigurationError("Check the database connection settings.") from exc
    role = params.get("user", "").split(".")[0]
    if role != expected_role:
        raise ConfigurationError(f"Use the dedicated {expected_role} database login.")
    host = params.get("host", "")
    local = is_local_host(host)
    if not local and params.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise ConfigurationError("Remote database connections require SSL.")
    if host.endswith("supabase.com") and (
        not host.endswith(".pooler.supabase.com") or params.get("port", "5432") != "5432"
    ):
        raise ConfigurationError("Use the Supabase Session pooler on port 5432.")
    if host.endswith(".supabase.co"):
        raise ConfigurationError("Use the Supabase Session pooler, not Direct connection.")
    return params


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


class QueryRunner:
    def __init__(self, url):
        self.url = url

    def run(self, sql_text):
        query = prepare_query(sql_text)
        validate_database_url(self.url, "treasury_reader")
        try:
            with psycopg.connect(self.url, connect_timeout=8) as conn:
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute("SET LOCAL statement_timeout = '5s'")
                conn.execute("SET LOCAL lock_timeout = '1s'")
                conn.execute("SET LOCAL search_path = pg_catalog, quiz_data")
                cursor = conn.execute(query, prepare=False)
                rows = cursor.fetchmany(MAX_ROWS + 1)
                return {
                    "columns": [column.name for column in cursor.description],
                    "rows": [[json_value(v) for v in row] for row in rows[:MAX_ROWS]],
                    "truncated": len(rows) > MAX_ROWS,
                }
        except psycopg.errors.QueryCanceled as exc:
            raise QueryError("The query exceeded the 5-second limit. Try a smaller query.") from exc
        except psycopg.OperationalError as exc:
            raise ConfigurationError("The database is unavailable. Please try again shortly.") from exc
        except psycopg.Error as exc:
            # Do not expose connection strings, credentials, or server diagnostics.
            raise QueryError("PostgreSQL rejected the query. Check column names, types and grouping.") from exc


class QuizStore:
    def __init__(self, url):
        self.url = url

    def _connect(self):
        validate_database_url(self.url, "treasury_writer")
        return psycopg.connect(self.url, connect_timeout=8)

    def save(self, owner_id, quiz, quiz_id=None):
        quiz_id = str(UUID(quiz_id)) if quiz_id else str(uuid4())
        # All data values are bound parameters; a title such as O'Reilly is data.
        with self._connect() as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            row = conn.execute(
                """INSERT INTO quiz_app.quizzes (id, owner_id, document)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (id) DO UPDATE
                   SET document = EXCLUDED.document, updated_at = now()
                   WHERE quizzes.owner_id = EXCLUDED.owner_id
                   RETURNING id""",
                (quiz_id, owner_id, Jsonb(quiz)),
            ).fetchone()
        if row is None:
            raise PermissionError("This quiz belongs to another user.")
        return str(row[0])

    def list(self, owner_id):
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, document->>'title', updated_at
                   FROM quiz_app.quizzes WHERE owner_id = %s
                   ORDER BY updated_at DESC LIMIT 50""", (owner_id,),
            ).fetchall()
        return [{"id": str(r[0]), "title": r[1], "updated_at": r[2].isoformat()} for r in rows]

    def get(self, owner_id, quiz_id):
        quiz_id = str(UUID(quiz_id))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT document FROM quiz_app.quizzes WHERE id = %s AND owner_id = %s",
                (quiz_id, owner_id),
            ).fetchone()
        return row[0] if row else None
