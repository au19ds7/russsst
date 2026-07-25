import json
import sqlite3
from contextlib import closing

DB_PATH = "/data/rustplus.db"


def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_link (
                tg_id INTEGER PRIMARY KEY,
                android_id TEXT,
                security_token TEXT,
                fcm_token TEXT,
                expo_token TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                fcm_credentials TEXT,       -- json: android_id/security_token/fcm_token/expo_token
                steam_auth_token TEXT,
                linked_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                tg_id INTEGER,
                ip TEXT,
                port TEXT,
                player_id TEXT,
                player_token TEXT,
                name TEXT,
                paired_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tg_id, ip, port)
            )
        """)
        conn.commit()


def save_pending_link(tg_id, android_id, security_token, fcm_token, expo_token):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pending_link (tg_id, android_id, security_token, fcm_token, expo_token) "
            "VALUES (?, ?, ?, ?, ?)",
            (tg_id, android_id, security_token, fcm_token, expo_token),
        )
        conn.commit()


def get_pending_link(tg_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT android_id, security_token, fcm_token, expo_token FROM pending_link WHERE tg_id = ?",
            (tg_id,),
        ).fetchone()
        return row


def save_user(tg_id, fcm_credentials: dict, steam_auth_token: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO users (tg_id, fcm_credentials, steam_auth_token) VALUES (?, ?, ?)",
            (tg_id, json.dumps(fcm_credentials), steam_auth_token),
        )
        conn.execute("DELETE FROM pending_link WHERE tg_id = ?", (tg_id,))
        conn.commit()


def get_user(tg_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT fcm_credentials, steam_auth_token FROM users WHERE tg_id = ?", (tg_id,)
        ).fetchone()
        if not row:
            return None
        return {"fcm_credentials": json.loads(row[0]), "steam_auth_token": row[1]}


def get_all_users():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute("SELECT tg_id, fcm_credentials FROM users").fetchall()
        return [(r[0], json.loads(r[1])) for r in rows]


def save_server(tg_id, ip, port, player_id, player_token, name=""):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO servers (tg_id, ip, port, player_id, player_token, name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tg_id, ip, port, player_id, player_token, name),
        )
        conn.commit()


def get_servers(tg_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT ip, port, player_id, player_token, name FROM servers WHERE tg_id = ?",
            (tg_id,),
        ).fetchall()
        return rows
