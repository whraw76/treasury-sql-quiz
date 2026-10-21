import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app import create_app
from auth import AuthError

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def quiz():
    return json.loads((Path(__file__).resolve().parents[1] / "data/quiz.json").read_text())


class FakeAuth:
    def login(self, email, password):
        if password != "valid-password":
            raise AuthError("Invalid credentials")
        return {"access_token": "other-token" if email == "other@example.com" else "valid-token"}

    def user(self, token):
        if token not in {"valid-token", "other-token"}:
            raise AuthError("Session expired")
        return {"id": OTHER if token == "other-token" else OWNER, "email": "student@example.com"}

    def signup(self, email, password):
        return {"user": {"id": OWNER}}

    def logout(self, token):
        pass


class FakeRunner:
    def __init__(self, quiz):
        self.answers = {q["reference_sql"]: q["expected"] for q in quiz["questions"]}
        self.calls = []

    def run(self, sql):
        from query_policy import prepare_query
        prepare_query(sql)
        self.calls.append(sql)
        return copy.deepcopy(self.answers.get(sql, {"columns": ["value"], "rows": [[1]], "truncated": False}))


class FakeStore:
    def __init__(self):
        self.rows = {}

    def save(self, owner, document, quiz_id=None):
        quiz_id = quiz_id or str(uuid4())
        if quiz_id in self.rows and self.rows[quiz_id][0] != owner:
            raise PermissionError("Not your quiz")
        self.rows[quiz_id] = (owner, copy.deepcopy(document))
        return quiz_id

    def get(self, owner, quiz_id):
        row = self.rows.get(quiz_id)
        return copy.deepcopy(row[1]) if row and row[0] == owner else None

    def list(self, owner):
        return [{"id": key, "title": value[1]["title"]} for key, value in self.rows.items() if value[0] == owner]


class FakeAudit:
    def __init__(self):
        self.events = []

    def query(self, actor_id, sql_text, outcome, details):
        self.events.append({"actor_id": actor_id, "sql_text": sql_text,
                            "outcome": outcome, "details": copy.deepcopy(details)})


@pytest.fixture
def application(quiz):
    return create_app({
        "TESTING": True, "SECRET_KEY": "test-only-not-a-production-secret",
        "AUTH": FakeAuth(), "RUNNER": FakeRunner(quiz), "STORE": FakeStore(),
        "AUDIT": FakeAudit(),
    })


@pytest.fixture
def client(application):
    return application.test_client()


@pytest.fixture
def headers(client):
    return {"X-CSRF-Token": client.get("/api/bootstrap").json["csrf_token"]}


@pytest.fixture
def signed_in(client, headers):
    response = client.post("/api/auth/login", headers=headers, json={"email": "a@example.com", "password": "valid-password"})
    assert response.status_code == 200
    return client, headers
