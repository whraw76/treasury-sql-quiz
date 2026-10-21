import copy

import pytest

from query_policy import MAX_SQL_LENGTH

from tests.conftest import OWNER


def test_public_quiz_has_20_points_and_five_complete_hints(client):
    data = client.get("/api/bootstrap").json
    questions = data["quiz"]["questions"]
    assert len(questions) == 5
    assert sum(q["points"] for q in questions) == 20
    assert all(q["reference_sql"] and q["expected"]["rows"] for q in questions)


def test_guest_cannot_bypass_ui_to_query_or_save(client, headers, application, quiz):
    assert client.post("/api/query", headers=headers, json={"sql": "SELECT * FROM yields"}).status_code == 401
    assert client.post("/api/quizzes", headers=headers, json={"quiz": quiz}).status_code == 401
    assert client.get("/api/quizzes").status_code == 401
    assert application.config["RUNNER"].calls == []
    assert application.config["STORE"].rows == {}


def test_csrf_is_required_even_with_a_valid_login(signed_in):
    client, headers = signed_in
    assert client.post("/api/query", json={"sql": "SELECT * FROM yields"}).status_code == 403
    assert client.post("/api/query", headers=headers, json={"sql": "SELECT * FROM yields"}).status_code == 200


def test_invalid_login_does_not_create_session(client, headers):
    assert client.post("/api/auth/login", headers=headers, json={"email": "a@example.com", "password": "wrong"}).status_code == 401
    assert client.get("/api/me").json == {"user": None}


def test_expired_token_is_rejected_by_server(signed_in, application):
    client, headers = signed_in
    with client.session_transaction() as session:
        session["access_token"] = "expired-token"
    response = client.post("/api/query", headers=headers, json={"sql": "SELECT * FROM yields"})
    assert response.status_code == 401
    assert application.config["RUNNER"].calls == []


def test_signed_in_query_returns_the_database_result(signed_in, quiz):
    client, headers = signed_in
    q = quiz["questions"][0]
    assert client.post("/api/query", headers=headers, json={"sql": q["reference_sql"]}).json == q["expected"]


def test_save_recomputes_hints_and_uses_verified_owner(signed_in, application, quiz):
    client, headers = signed_in
    forged = copy.deepcopy(quiz)
    forged["questions"][0]["expected"]["rows"] = [["fake", 999]]
    response = client.post("/api/quizzes", headers=headers, json={"quiz": forged, "owner_id": "forged-user"})
    assert response.status_code == 201
    saved_id = response.json["id"]
    assert application.config["STORE"].rows[saved_id][0] == OWNER
    assert response.json["quiz"]["questions"][0]["expected"] == quiz["questions"][0]["expected"]
    assert len(application.config["RUNNER"].calls) == 5
    assert client.get(f"/api/quizzes/{saved_id}").json["quiz"] == response.json["quiz"]


def test_other_user_cannot_read_or_overwrite_saved_quiz(signed_in, quiz):
    client, headers = signed_in
    quiz["answers"] = ["SELECT 60 -- private answer", "", "", "", ""]
    saved_id = client.post("/api/quizzes", headers=headers, json={"quiz": quiz}).json["id"]
    client.post("/api/auth/login", headers=headers, json={"email": "other@example.com", "password": "valid-password"})
    assert client.get(f"/api/quizzes/{saved_id}").status_code == 404
    assert client.get("/api/quizzes").json["quizzes"] == []
    assert client.post("/api/quizzes", headers=headers, json={"id": saved_id, "quiz": quiz}).status_code == 403


def test_logout_blocks_query_and_save(signed_in, quiz):
    client, headers = signed_in
    assert client.post("/api/auth/logout", headers=headers, json={}).status_code == 200
    assert client.post("/api/query", headers=headers, json={"sql": "SELECT 1"}).status_code == 401
    assert client.post("/api/quizzes", headers=headers, json={"quiz": quiz}).status_code == 401


def test_save_rejects_wrong_points_and_invalid_id(signed_in, quiz):
    client, headers = signed_in
    assert client.post("/api/quizzes", headers=headers, json={"id": "bad-id", "quiz": quiz}).status_code == 400
    quiz["questions"][0]["points"] = 99
    assert client.post("/api/quizzes", headers=headers, json={"quiz": quiz}).status_code == 400


def test_invalid_reference_is_not_saved(signed_in, application, quiz):
    client, headers = signed_in
    quiz["questions"][3]["reference_sql"] = "DROP TABLE yields"
    assert client.post("/api/quizzes", headers=headers, json={"quiz": quiz}).status_code == 400
    assert application.config["STORE"].rows == {}


def test_json_errors_are_usable_and_responses_not_cached(signed_in):
    client, headers = signed_in
    response = client.post("/api/query", headers=headers, json=[])
    assert response.status_code == 400
    assert response.json["error"]
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_all_five_answer_drafts_roundtrip_without_execution(signed_in, application, quiz):
    client, headers = signed_in
    answers = [
        "SELECT date, yield_percent\nFROM yields;\n",
        "SELECT -- unfinished",
        "",  # An unanswered question is still saved in its original position.
        "SELECT 'student''s note: 收益率';",
        "DROP TABLE yields;",  # Stored as text only; never passed to the runner.
    ]
    quiz["answers"] = answers
    response = client.post("/api/quizzes", headers=headers, json={"quiz": quiz})
    assert response.status_code == 201
    saved_id = response.json["id"]
    assert response.json["quiz"]["answers"] == answers
    assert client.get(f"/api/quizzes/{saved_id}").json["quiz"]["answers"] == answers
    assert application.config["RUNNER"].calls == [q["reference_sql"] for q in quiz["questions"]]


def test_resaving_updates_answers_without_creating_another_quiz(signed_in, quiz):
    client, headers = signed_in
    quiz["answers"] = ["SELECT", "", "", "", ""]
    saved_id = client.post("/api/quizzes", headers=headers, json={"quiz": quiz}).json["id"]
    quiz["answers"] = ["SELECT COUNT(*) FROM yields;", "", "", "", "SELECT 5;"]
    updated = client.post("/api/quizzes", headers=headers, json={"id": saved_id, "quiz": quiz})
    assert updated.status_code == 201
    assert updated.json["id"] == saved_id
    assert len(client.get("/api/quizzes").json["quizzes"]) == 1
    assert client.get(f"/api/quizzes/{saved_id}").json["quiz"]["answers"] == quiz["answers"]


@pytest.mark.parametrize("answers", [None, "SELECT 1", [], [""] * 4, [""] * 6,
                                     [None] + [""] * 4, [7] + [""] * 4,
                                     ["x" * (MAX_SQL_LENGTH + 1)] + [""] * 4])
def test_invalid_answer_payload_is_rejected_before_running_or_saving(signed_in, application, quiz, answers):
    client, headers = signed_in
    quiz["answers"] = answers
    response = client.post("/api/quizzes", headers=headers, json={"quiz": quiz})
    assert response.status_code == 400
    assert "answer" in response.json["error"].lower()
    assert application.config["STORE"].rows == {}
    assert application.config["RUNNER"].calls == []


def test_legacy_saved_quiz_opens_with_five_blank_answers(signed_in, application, quiz):
    client, _ = signed_in
    saved_id = application.config["STORE"].save(OWNER, quiz)
    reopened = client.get(f"/api/quizzes/{saved_id}")
    assert reopened.status_code == 200
    assert reopened.json["quiz"]["answers"] == [""] * 5
    assert reopened.json["quiz"]["questions"] == quiz["questions"]


def test_missing_answers_default_to_blank_and_length_boundary_is_allowed(signed_in, quiz):
    client, headers = signed_in
    saved = client.post("/api/quizzes", headers=headers, json={"quiz": quiz})
    assert saved.json["quiz"]["answers"] == [""] * 5
    quiz["answers"] = ["x" * MAX_SQL_LENGTH] + [""] * 4
    boundary = client.post("/api/quizzes", headers=headers, json={"quiz": quiz})
    assert boundary.status_code == 201
    assert boundary.json["quiz"]["answers"] == quiz["answers"]
