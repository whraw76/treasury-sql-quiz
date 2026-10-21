import pytest
import sqlglot

from db import ConfigurationError, validate_database_url
from query_policy import QueryError, prepare_query


@pytest.mark.parametrize("sql", [
    "DELETE FROM yields", "DROP TABLE yields", "SELECT * FROM yields; DELETE FROM yields",
    "SELECT * INTO stolen FROM yields", "SELECT pg_sleep(10)",
    "SELECT pg_catalog.set_config('search_path','public',false)",
    "SELECT * FROM auth.users", "SELECT * FROM quiz_app.quizzes", "SELECT * FROM pg_roles",
    "SELECT * FROM public.yields", "SELECT * FROM yields FOR UPDATE", "SET ROLE postgres",
    "WITH x AS (DELETE FROM yields RETURNING *) SELECT * FROM x",
    "SELECT current_setting('application_name')", "SELECT * FROM yields LIMIT -1",
    "SELECT * FROM yields LIMIT ALL", "", None,
])
def test_unsafe_or_out_of_scope_sql_is_rejected(sql):
    with pytest.raises(QueryError):
        prepare_query(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM yields",
    "SELECT maturity_years, COUNT(*) FROM yields GROUP BY maturity_years",
    "SELECT * FROM yields WHERE yield_percent BETWEEN 3 AND 5 ORDER BY date",
    "WITH recent AS (SELECT * FROM yields WHERE date > '2024-01-01') SELECT * FROM recent",
    "SELECT * FROM yields WHERE maturity_years IN (2,10)",
    "SELECT * FROM yields WHERE yield_percent > (SELECT AVG(yield_percent) FROM yields)",
    "SELECT 'DROP TABLE yields' AS harmless_text",
    "SELECT * FROM yields -- DELETE is only a comment\nLIMIT 3",
])
def test_equivalent_select_forms_are_accepted(sql):
    assert prepare_query(sql).startswith("SELECT") or prepare_query(sql).startswith("WITH")


def test_reference_queries_and_row_limits(quiz):
    for q in quiz["questions"]:
        prepared = prepare_query(q["reference_sql"])
        assert "quiz_data.yields" in prepared
        assert int(sqlglot.parse_one(prepared, read="postgres").args["limit"].expression.this) <= 201
    assert prepare_query("SELECT * FROM yields LIMIT 100000").endswith("LIMIT 201")
    assert prepare_query("SELECT * FROM yields LIMIT 2").endswith("LIMIT 2")


@pytest.mark.parametrize("url", [
    "", "postgresql://postgres:fake@x.pooler.supabase.com:5432/postgres?sslmode=require",
    "postgresql://treasury_reader.project:fake@x.pooler.supabase.com:5432/postgres",
    "postgresql://treasury_reader.project:fake@x.pooler.supabase.com:6543/postgres?sslmode=require",
    "postgresql://treasury_reader:fake@db.project.supabase.co:5432/postgres?sslmode=require",
])
def test_unsafe_connection_configuration_rejected(url):
    with pytest.raises(ConfigurationError):
        validate_database_url(url, "treasury_reader")


def test_session_pooler_with_restricted_role_and_ssl_accepted():
    url = "postgresql://treasury_reader.example:placeholder@aws-0-region.pooler.supabase.com:5432/postgres?sslmode=require"
    assert validate_database_url(url, "treasury_reader")["sslmode"] == "require"
