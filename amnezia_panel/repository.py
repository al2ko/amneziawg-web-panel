# region MODULE_CONTRACT [DOMAIN(9): Persistence; CONCEPT(9): AuditAndMetadata; TECH(9): SQLite]
## @modulecontract
## @purpose Сохранять метаданные клиентов, серверные сессии, попытки входа и неизменяемый аудит.
## @scope SQLite schema and parameterized repository operations.
## @input Validated domain values.
## @output Records and transactionally persisted state.
## @invariants SQL values always use bound parameters; audit rows are never updated.
## @rationale SQLite keeps deployment single-node and backup-friendly.
## @changes LAST_CHANGE: v1.0.0 initial persistence layer.
## @modulemap CLASS 10[Panel persistence gateway] => PanelRepository
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: SQLite, clients metadata, disabled peers, sessions, audit, login attempts
# STRUCTURE: ▶ validated values → parameterized transaction → SQLite → typed dictionaries

# BUG_FIX_CONTEXT: Future-import несовместим с предшествующим module contract; проект требует Python 3.11+, поэтому он не нужен.
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PanelRepository:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        """▶ database path → idempotent schema → ready repository."""
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    public_key TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    tunnel_ip TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    peer_block TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    csrf_token TEXT NOT NULL,
                    last_seen INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    ip TEXT NOT NULL,
                    attempted_at INTEGER NOT NULL,
                    successful INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_time ON login_attempts(ip, attempted_at);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at INTEGER NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(clients)")}
            if "notes" not in columns:
                db.execute("ALTER TABLE clients ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
            if "tags" not in columns:
                db.execute("ALTER TABLE clients ADD COLUMN tags TEXT NOT NULL DEFAULT ''")

    def upsert_client(self, public_key: str, name: str, tunnel_ip: str, enabled: bool = True, peer_block: str = "") -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO clients(public_key,name,tunnel_ip,enabled,peer_block,created_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(public_key) DO UPDATE SET
                name=excluded.name,tunnel_ip=excluded.tunnel_ip,enabled=excluded.enabled,
                peer_block=CASE WHEN excluded.peer_block='' THEN clients.peer_block ELSE excluded.peer_block END""",
                (public_key, name, tunnel_ip, int(enabled), peer_block, int(time.time())),
            )

    def get_clients(self) -> dict[str, dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT public_key,name,tunnel_ip,enabled,peer_block,notes,tags FROM clients").fetchall()
        return {row["public_key"]: dict(row) for row in rows}

    def get_client(self, public_key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM clients WHERE public_key=?", (public_key,)).fetchone()
        return dict(row) if row else None

    def find_by_name(self, name: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM clients WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def rename_client(self, public_key: str, name: str, peer_block: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE clients SET name=?,peer_block=? WHERE public_key=?", (name, peer_block, public_key))

    def set_enabled(self, public_key: str, enabled: bool, peer_block: str = "") -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE clients SET enabled=?,peer_block=CASE WHEN ?='' THEN peer_block ELSE ? END WHERE public_key=?",
                (int(enabled), peer_block, peer_block, public_key),
            )

    def update_client_details(self, public_key: str, notes: str, tags: str) -> None:
        with self._connect() as db:
            cursor = db.execute("UPDATE clients SET notes=?,tags=? WHERE public_key=?", (notes, tags, public_key))
            if cursor.rowcount != 1:
                raise KeyError("Клиент не найден")

    def delete_client(self, public_key: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM clients WHERE public_key=?", (public_key,))

    def create_session(self, token_hash: str, username: str, csrf_token: str, expires_at: int) -> None:
        now = int(time.time())
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (token_hash, username, csrf_token, now, expires_at))

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()
        return dict(row) if row else None

    def touch_session(self, token_hash: str, last_seen: int, expires_at: int) -> None:
        with self._connect() as db:
            db.execute("UPDATE sessions SET last_seen=?,expires_at=? WHERE token_hash=?", (last_seen, expires_at, token_hash))

    def delete_session(self, token_hash: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def record_login(self, ip: str, successful: bool) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO login_attempts VALUES(?,?,?)", (ip, int(time.time()), int(successful)))

    def failed_login_count(self, ip: str, since: int) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) count FROM login_attempts WHERE ip=? AND successful=0 AND attempted_at>=?",
                (ip, since),
            ).fetchone()
        return int(row["count"])

    def audit(self, actor: str, action: str, target: str, ip: str, details: dict | None = None) -> None:
        safe_details = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)
        with self._connect() as db:
            db.execute(
                "INSERT INTO audit(created_at,actor,action,target,ip,details) VALUES(?,?,?,?,?,?)",
                (int(time.time()), actor, action, target, ip, safe_details),
            )
        logger.info("[IMP:8][audit][RECORDED] actor=%s action=%s target=%s ip=%s", actor, action, target, ip)

    def recent_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._connect() as db:
            rows = db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def dump_sql(self) -> str:
        """▶ live WAL database → consistent read transaction → portable SQL backup."""
        with self._connect() as db:
            return "\n".join(db.iterdump()) + "\n"
