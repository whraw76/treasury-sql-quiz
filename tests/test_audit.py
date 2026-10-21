import pytest

from db import ConfigurationError
from tests.conftest import OWNER


def test_query_log_uses_verified_identity_and_row_count(signed_in, application, quiz):
    client, headers = signed_in
    sql = quiz["questions"][0]["reference_sql"]
    response = client.post("/api/query", headers=headers, json={"sql": sql, "actor_id": "forged"})
    assert response.status_code == 200
    assert application.config["AUDIT"].events == [{
        "actor_id": OWNER, "sql_text": sql, "outcome": "success",
        "details": {"returned_rows": 5, "truncated": False},
    }]


def test_rejected_query_is_recorded_without_execution(signed_in, application):
    client, headers = signed_in
    response = client.post("/api/query", headers=headers, json={"sql": "DROP TABLE yields"})
    assert response.status_code == 400
    assert application.config["RUNNER"].calls == []
    assert application.config["AUDIT"].events[0]["outcome"] == "rejected"
    assert application.config["AUDIT"].events[0]["sql_text"] == "DROP TABLE yields"


def test_database_outage_is_recorded_without_sensitive_error(signed_in, application, monkeypatch):
    def unavailable(sql):
        raise ConfigurationError("The database is unavailable.")
    monkeypatch.setattr(application.config["RUNNER"], "run", unavailable)
    client, headers = signed_in
    assert client.post("/api/query", headers=headers, json={"sql": "SELECT 1"}).status_code == 503
    event = application.config["AUDIT"].events[0]
    assert event["outcome"] == "failed"
    assert event["details"] == {"error_type": "ConfigurationError"}


def test_log_outage_does_not_report_query_success(signed_in, application, monkeypatch):
    def unavailable(*args):
        raise ConfigurationError("The query could not be recorded. Please try again.")
    monkeypatch.setattr(application.config["AUDIT"], "query", unavailable)
    client, headers = signed_in
    response = client.post("/api/query", headers=headers, json={"sql": "SELECT 1"})
    assert response.status_code == 503
    assert "rows" not in response.json


def test_guest_cannot_create_audit_event(client, headers, application):
    assert client.post("/api/query", headers=headers, json={"sql": "SELECT 1"}).status_code == 401
    assert application.config["AUDIT"].events == []


@pytest.mark.parametrize("sql", [None, 123, "", " " * 4, "x" * 8001])
def test_invalid_query_payload_does_not_create_log(signed_in, application, sql):
    client, headers = signed_in
    assert client.post("/api/query", headers=headers, json={"sql": sql}).status_code == 400
    assert application.config["AUDIT"].events == []
