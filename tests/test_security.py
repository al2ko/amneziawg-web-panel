# region MODULE_CONTRACT [DOMAIN(10): Testing; CONCEPT(10): SecurityControls; TECH(9): pytest]
## @modulecontract
## @purpose Проверить Argon2, opaque sessions, CSRF, timeout и brute-force protection.
## @scope AuthService direct imports with temporary SQLite.
## @input Temporary database and known credentials.
## @output Security assertions and LDD telemetry.
## @invariants Tests never persist plaintext passwords.
## @changes LAST_CHANGE: v1.0.0 initial security tests.
## @modulemap FUNC 10[Authentication flow] => test_login_session_csrf_logout
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: pytest, Argon2, CSRF, rate limit, session timeout
# STRUCTURE: ▶ credentials → login → opaque session → CSRF → logout; failures ×5 → block

import logging
import sqlite3
from pathlib import Path

from amnezia_panel.config import Settings
from amnezia_panel.repository import PanelRepository
from amnezia_panel.security import AuthService


def auth_fixture(tmp_path: Path):
    password = "correct horse battery staple"
    settings = Settings(
        secret_key="s" * 32, admin_username="admin", password_hash=AuthService.hash_password(password),
        database_path=tmp_path / "auth.db", config_path=tmp_path / "none.conf", clients_dir=tmp_path / "clients",
    )
    repository = PanelRepository(settings.database_path)
    repository.initialize()
    return AuthService(settings, repository), repository, password


def test_login_session_csrf_logout(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    auth, repository, password = auth_fixture(tmp_path)
    token, csrf = auth.login("admin", password, "127.0.0.1")
    record = auth.authenticate(token)
    assert record["username"] == "admin"
    assert auth.validate_csrf(record, csrf)
    assert not auth.validate_csrf(record, "wrong")
    assert token not in str(repository.get_session(auth._digest(token)))
    auth.logout(token, "127.0.0.1")
    assert auth.authenticate(token) is None
    important = [record.message for record in caplog.records if "[IMP:9]" in record.message]
    print("\n".join(important))
    assert any("[SUCCESS]" in message for message in important)


def test_rate_limit(tmp_path):
    auth, repository, _ = auth_fixture(tmp_path)
    for _ in range(auth.MAX_FAILURES):
        assert auth.login("admin", "wrong password", "203.0.113.8") is None
    assert auth.login("admin", "correct horse battery staple", "203.0.113.8") is None
    assert any(item["action"] == "login_blocked" for item in repository.recent_audit())


def test_session_expires_on_inactivity_policy(tmp_path):
    password = "correct horse battery staple"
    settings = Settings(
        secret_key="t" * 32, admin_username="admin", password_hash=AuthService.hash_password(password),
        database_path=tmp_path / "timeout.db", config_path=tmp_path / "none.conf", clients_dir=tmp_path / "clients",
        session_timeout=-1,
    )
    repository = PanelRepository(settings.database_path)
    repository.initialize()
    auth = AuthService(settings, repository)
    token, _ = auth.login("admin", password, "127.0.0.1")
    assert auth.authenticate(token) is None


def test_existing_database_adds_client_notes_and_tags(tmp_path):
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as db:
        db.execute(
            """CREATE TABLE clients (
                public_key TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, tunnel_ip TEXT NOT NULL,
                enabled INTEGER NOT NULL, peer_block TEXT NOT NULL, created_at INTEGER NOT NULL
            )"""
        )
        db.execute("INSERT INTO clients VALUES(?,?,?,?,?,?)", ("KEY", "phone", "10.8.1.2", 1, "[Peer]", 1))

    repository = PanelRepository(database_path)
    repository.initialize()
    repository.update_client_details("KEY", "Основной телефон", "личный")
    client = repository.get_client("KEY")
    assert client["notes"] == "Основной телефон"
    assert client["tags"] == "личный"
    assert client["expires_at"] is None
