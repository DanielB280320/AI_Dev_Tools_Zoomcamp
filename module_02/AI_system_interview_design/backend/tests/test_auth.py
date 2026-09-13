"""Interviewer accounts, password hashing and token scoping."""

from __future__ import annotations

from conftest import ALEX, DEMO_PASSWORD, all_rows, auth, create_session, join, login
from fastapi.testclient import TestClient

from app import tables
from app.auth import hash_password, verify_password


class TestPasswordHashing:
    def test_hash_is_salted_and_verifiable(self) -> None:
        first = hash_password("correct horse battery staple", iterations=1000)
        second = hash_password("correct horse battery staple", iterations=1000)

        assert first != second, "a fresh salt must make every digest unique"
        assert verify_password("correct horse battery staple", first)
        assert verify_password("correct horse battery staple", second)

    def test_hash_does_not_contain_the_password(self) -> None:
        encoded = hash_password("hunter2hunter2", iterations=1000)

        assert "hunter2hunter2" not in encoded
        assert encoded.startswith("pbkdf2_sha256$1000$")

    def test_wrong_password_and_corrupt_hash_both_fail(self) -> None:
        encoded = hash_password("the right one", iterations=1000)

        assert not verify_password("the wrong one", encoded)
        assert not verify_password("the right one", "not-a-hash")
        assert not verify_password("the right one", "md5$1$aa$bb")

    def test_seeded_accounts_store_only_hashes(self, client: TestClient) -> None:
        for account in all_rows(tables.Account):
            assert DEMO_PASSWORD not in account.password_hash
            assert verify_password(DEMO_PASSWORD, account.password_hash)


class TestRegister:
    def test_registers_and_signs_in(self, client: TestClient) -> None:
        response = client.post(
            "/auth/register",
            json={"email": "New.Person@Example.com ", "password": "a-good-password", "name": "Nia"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["interviewer"]["email"] == "new.person@example.com", "email is normalised"
        assert body["interviewer"]["name"] == "Nia"
        assert body["token"]

        me = client.get("/auth/me", headers=auth(body["token"]))
        assert me.json()["email"] == "new.person@example.com"

    def test_duplicate_email_conflicts(self, client: TestClient) -> None:
        response = client.post(
            "/auth/register", json={"email": ALEX, "password": "another-password"}
        )

        assert response.status_code == 409
        assert response.json()["error"] == "email_taken"

    def test_short_password_is_rejected(self, client: TestClient) -> None:
        response = client.post("/auth/register", json={"email": "x@y.dev", "password": "short"})

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"

    def test_invalid_email_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/auth/register", json={"email": "not-an-email", "password": "a-good-password"}
        )

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_email"

    def test_name_falls_back(self, client: TestClient) -> None:
        response = client.post(
            "/auth/register", json={"email": "n@y.dev", "password": "a-good-password", "name": "  "}
        )

        assert response.json()["interviewer"]["name"] == "Interviewer"


class TestLogin:
    def test_login_is_case_insensitive_on_email(self, client: TestClient) -> None:
        response = client.post(
            "/auth/login", json={"email": "ALEX@loopboard.dev", "password": DEMO_PASSWORD}
        )

        assert response.status_code == 200
        assert response.json()["interviewer"]["name"] == "Alex Rivera"

    def test_wrong_password_is_unauthorized(self, client: TestClient) -> None:
        response = client.post("/auth/login", json={"email": ALEX, "password": "wrong"})

        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"

    def test_unknown_email_is_indistinguishable(self, client: TestClient) -> None:
        unknown = client.post("/auth/login", json={"email": "nobody@nowhere.dev", "password": "x"})
        wrong = client.post("/auth/login", json={"email": ALEX, "password": "x"})

        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()

    def test_logout_revokes_the_token(self, client: TestClient) -> None:
        token = login(client)

        assert client.post("/auth/logout", headers=auth(token)).status_code == 204
        assert client.get("/auth/me", headers=auth(token)).status_code == 401


class TestTokenScoping:
    def test_dashboard_rejects_missing_and_bogus_tokens(self, client: TestClient) -> None:
        assert client.get("/sessions").status_code == 401
        assert client.get("/sessions", headers=auth("nonsense")).status_code == 401
        assert client.get("/sessions", headers={"Authorization": "Basic abc"}).status_code == 401

    def test_dashboard_rejects_a_participant_token(self, client: TestClient) -> None:
        host_token = login(client)
        session_id = create_session(client, host_token)
        candidate = join(client, session_id, "Jordan", "candidate")

        response = client.get("/sessions", headers=candidate.headers)

        assert response.status_code == 401

    def test_participant_token_is_scoped_to_its_session(self, client: TestClient) -> None:
        host_token = login(client)
        mine = create_session(client, host_token)
        theirs = create_session(client, host_token)
        candidate = join(client, mine, "Jordan", "candidate")

        ok = client.get(f"/sessions/{mine}/canvas", headers=candidate.headers)
        blocked = client.get(f"/sessions/{theirs}/canvas", headers=candidate.headers)

        assert ok.status_code == 200
        assert blocked.status_code == 403
        assert blocked.json()["error"] == "wrong_session"

    def test_interviewer_token_cannot_reach_another_account_session(
        self, client: TestClient
    ) -> None:
        sam_token = login(client, "sam@loopboard.dev")
        alex_session = create_session(client, login(client))

        response = client.get(f"/sessions/{alex_session}/canvas", headers=auth(sam_token))

        assert response.status_code == 403
        assert response.json()["error"] == "not_session_owner"

    def test_error_bodies_use_the_contract_shape(self, client: TestClient) -> None:
        body = client.get("/sessions").json()

        assert set(body) <= {"error", "message"}
        assert isinstance(body["error"], str)
