"""
SQLite database — barcha ma'lumotlar shu yerda saqlanadi.
"""
import sqlite3
import os
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "bot.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            session_name TEXT    NOT NULL UNIQUE,
            phone        TEXT    NOT NULL,
            name         TEXT    DEFAULT '',
            status       TEXT    DEFAULT 'active',
            added_at     TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS groups (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            identifier TEXT    NOT NULL,
            title      TEXT    DEFAULT '',
            added_at   TEXT    DEFAULT (datetime('now')),
            UNIQUE(user_id, identifier)
        );

        CREATE TABLE IF NOT EXISTS campaigns (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL,
            name           TEXT    NOT NULL,
            message_text   TEXT    NOT NULL,
            interval_min   INTEGER NOT NULL DEFAULT 30,
            acc_interval_s INTEGER NOT NULL DEFAULT 2,
            font_style     TEXT    NOT NULL DEFAULT 'none',
            is_active      INTEGER NOT NULL DEFAULT 1,
            next_run       TEXT,
            last_run       TEXT,
            created_at     TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS campaign_accounts (
            campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            account_id   INTEGER NOT NULL REFERENCES accounts(id)  ON DELETE CASCADE,
            PRIMARY KEY (campaign_id, account_id)
        );

        CREATE TABLE IF NOT EXISTS campaign_groups (
            campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            group_id     INTEGER NOT NULL REFERENCES groups(id)    ON DELETE CASCADE,
            PRIMARY KEY (campaign_id, group_id)
        );

        CREATE TABLE IF NOT EXISTS send_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            account_id  INTEGER,
            group_id    INTEGER,
            status      TEXT,
            error       TEXT,
            sent_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS allowed_users (
            user_id   INTEGER PRIMARY KEY,
            name      TEXT    DEFAULT '',
            username  TEXT    DEFAULT '',
            is_paused INTEGER DEFAULT 0,
            added_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS sent_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            session_name TEXT    NOT NULL,
            chat_id      INTEGER NOT NULL,
            message_id   INTEGER NOT NULL,
            sent_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_sent_messages_time ON sent_messages(sent_at);

        CREATE TABLE IF NOT EXISTS user_settings (
            user_id         INTEGER PRIMARY KEY,
            auto_delete_24h INTEGER DEFAULT 1,
            night_mode      INTEGER DEFAULT 0,
            speed_mode      TEXT    DEFAULT 'normal',
            notify_finish   INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS error_notifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            error_type  TEXT NOT NULL,
            target_id   INTEGER NOT NULL,
            notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, error_type, target_id)
        );
        CREATE INDEX IF NOT EXISTS idx_err_notif_time ON error_notifications(notified_at);
        """)

    # Eski DB uchun yangi ustunlarni qo'shish (migration)
    with get_conn() as conn:
        for col, col_type in [("acc_interval_s", "INTEGER NOT NULL DEFAULT 2"), ("font_style", "TEXT NOT NULL DEFAULT 'none'")]:
            try:
                conn.execute(f"ALTER TABLE campaigns ADD COLUMN {col} {col_type}")
            except Exception:
                pass

        for col, col_type in [("name", "TEXT DEFAULT ''"), ("username", "TEXT DEFAULT ''"), ("is_paused", "INTEGER DEFAULT 0")]:
            try:
                conn.execute(f"ALTER TABLE allowed_users ADD COLUMN {col} {col_type}")
            except Exception:
                pass

        # Boshlang'ich ruxsat etilgan foydalanuvchilar va sozlamalar migratsiyasi
        try:
            import config
            cur = conn.execute("SELECT COUNT(*) as cnt FROM allowed_users")
            if cur.fetchone()["cnt"] == 0:
                for uid in getattr(config, "ALLOWED_USERS", []):
                    conn.execute("INSERT OR IGNORE INTO allowed_users (user_id) VALUES (?)", (uid,))
            
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("max_accounts", str(getattr(config, "MAX_ACCOUNTS_PER_USER", 20))))
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("admin_password", getattr(config, "ADMIN_PASSWORD", "Senior0307")))
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("global_pause", "0"))
        except Exception as e:
            print(f"Migration error: {e}")


# ── Accounts ──────────────────────────────────────────────────────────────────

def add_account(user_id: int, session_name: str, phone: str, name: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR REPLACE INTO accounts(user_id, session_name, phone, name, status) VALUES(?,?,?,?,'active')",
            (user_id, session_name, phone, name),
        )
        return cur.lastrowid


def get_accounts(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM accounts WHERE user_id=? AND status='active' ORDER BY id",
            (user_id,),
        ).fetchall()


def get_account(account_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()


def delete_account(account_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM accounts WHERE id=? AND user_id=?", (account_id, user_id))


def count_accounts(user_id: int) -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE user_id=? AND status='active'", (user_id,)
        ).fetchone()[0]


# ── Groups ────────────────────────────────────────────────────────────────────

def add_group(user_id: int, identifier: str, title: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO groups(user_id, identifier, title) VALUES(?,?,?)",
            (user_id, identifier, title),
        )
        if cur.lastrowid:
            return cur.lastrowid
        return conn.execute(
            "SELECT id FROM groups WHERE user_id=? AND identifier=?", (user_id, identifier)
        ).fetchone()["id"]


def get_groups(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM groups WHERE user_id=? ORDER BY id", (user_id,)
        ).fetchall()


def get_group(group_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()


def delete_group(group_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM groups WHERE id=? AND user_id=?", (group_id, user_id))


# ── Campaigns ─────────────────────────────────────────────────────────────────

def create_campaign(user_id: int, name: str, message_text: str,
                    interval_min: int, acc_interval_s: int = 2,
                    font_style: str = "none") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO campaigns(user_id, name, message_text, interval_min, acc_interval_s, font_style) "
            "VALUES(?,?,?,?,?,?)",
            (user_id, name, message_text, interval_min, acc_interval_s, font_style),
        )
        return cur.lastrowid


def get_campaigns(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM campaigns WHERE user_id=? ORDER BY id", (user_id,)
        ).fetchall()


def get_campaign(campaign_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()


def get_all_campaigns(user_id: int) -> list[sqlite3.Row]:
    """Foydalanuvchining barcha kampaniyalari."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM campaigns WHERE user_id=? ORDER BY id", (user_id,)
        ).fetchall()


def update_campaign_field(campaign_id: int, field: str, value):
    allowed = {"name", "message_text", "interval_min", "acc_interval_s",
               "font_style", "is_active", "next_run", "last_run"}
    if field not in allowed:
        raise ValueError(f"Unknown field: {field}")
    with get_conn() as conn:
        conn.execute(f"UPDATE campaigns SET {field}=? WHERE id=?", (value, campaign_id))


def update_all_campaigns_text(user_id: int, new_text: str):
    """Foydalanuvchining BARCHA kampaniyalari matnini o'zgartiradi."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE campaigns SET message_text=? WHERE user_id=?",
            (new_text, user_id),
        )


def delete_campaign(campaign_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM campaigns WHERE id=? AND user_id=?", (campaign_id, user_id))


def set_campaign_accounts(campaign_id: int, account_ids: list[int]):
    with get_conn() as conn:
        conn.execute("DELETE FROM campaign_accounts WHERE campaign_id=?", (campaign_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO campaign_accounts(campaign_id, account_id) VALUES(?,?)",
            [(campaign_id, aid) for aid in account_ids],
        )


def set_campaign_groups(campaign_id: int, group_ids: list[int]):
    with get_conn() as conn:
        conn.execute("DELETE FROM campaign_groups WHERE campaign_id=?", (campaign_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO campaign_groups(campaign_id, group_id) VALUES(?,?)",
            [(campaign_id, gid) for gid in group_ids],
        )


def get_campaign_accounts(campaign_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT a.* FROM accounts a
               JOIN campaign_accounts ca ON ca.account_id=a.id
               WHERE ca.campaign_id=? AND a.status='active'""",
            (campaign_id,),
        ).fetchall()


def get_campaign_groups(campaign_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT g.* FROM groups g
               JOIN campaign_groups cg ON cg.group_id=g.id
               WHERE cg.campaign_id=?""",
            (campaign_id,),
        ).fetchall()


def get_due_campaigns() -> list[sqlite3.Row]:
    """next_run vaqti o'tgan yoki NULL bo'lgan aktiv kampaniyalar."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM campaigns
               WHERE is_active=1
               AND (next_run IS NULL OR next_run <= datetime('now'))
               ORDER BY next_run""",
        ).fetchall()


def log_send(campaign_id: int, account_id: int, group_id: int, status: str, error: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO send_log(campaign_id,account_id,group_id,status,error) VALUES(?,?,?,?,?)",
            (campaign_id, account_id, group_id, status, error),
        )


def get_statistics(user_id: int) -> dict:
    with get_conn() as conn:
        acc_total = conn.execute("SELECT COUNT(*) FROM accounts WHERE user_id=?", (user_id,)).fetchone()[0]
        acc_active = conn.execute("SELECT COUNT(*) FROM accounts WHERE user_id=? AND status='active'", (user_id,)).fetchone()[0]
        
        grp_total = conn.execute("SELECT COUNT(*) FROM groups WHERE user_id=?", (user_id,)).fetchone()[0]
        
        camp_total = conn.execute("SELECT COUNT(*) FROM campaigns WHERE user_id=?", (user_id,)).fetchone()[0]
        camp_active = conn.execute("SELECT COUNT(*) FROM campaigns WHERE user_id=? AND is_active=1", (user_id,)).fetchone()[0]
        
        sent_today = conn.execute("""
            SELECT COUNT(*) FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            WHERE c.user_id=? AND sl.status='sent' AND date(sl.sent_at) = date('now')
        """, (user_id,)).fetchone()[0]
        
        failed_today = conn.execute("""
            SELECT COUNT(*) FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            WHERE c.user_id=? AND sl.status='failed' AND date(sl.sent_at) = date('now')
        """, (user_id,)).fetchone()[0]
        
        sent_total = conn.execute("""
            SELECT COUNT(*) FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            WHERE c.user_id=? AND sl.status='sent'
        """, (user_id,)).fetchone()[0]
        
        failed_total = conn.execute("""
            SELECT COUNT(*) FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            WHERE c.user_id=? AND sl.status='failed'
        """, (user_id,)).fetchone()[0]
        
        errors = conn.execute("""
            SELECT sl.error, sl.sent_at, g.title, g.identifier
            FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            LEFT JOIN groups g ON sl.group_id = g.id
            WHERE c.user_id=? AND sl.status='failed' AND sl.error != ''
            ORDER BY sl.id DESC LIMIT 5
        """, (user_id,)).fetchall()
        
        error_list = []
        for r in errors:
            error_list.append({
                "error": r["error"],
                "sent_at": r["sent_at"],
                "group": r["title"] or r["identifier"] or "Noma'lum"
            })
            
        return {
            "acc_total": acc_total,
            "acc_active": acc_active,
            "grp_total": grp_total,
            "camp_total": camp_total,
            "camp_active": camp_active,
            "sent_today": sent_today,
            "failed_today": failed_today,
            "sent_total": sent_total,
            "failed_total": failed_total,
            "recent_errors": error_list
        }


# ── Allowed Users & Settings (Secret Admin Panel) ─────────────────────────────

def is_user_allowed(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM allowed_users WHERE user_id=?", (user_id,)).fetchone()
        return row is not None


def add_allowed_user(user_id: int) -> bool:
    try:
        with get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO allowed_users (user_id) VALUES (?)", (user_id,))
        return True
    except Exception:
        return False


def remove_allowed_user(user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM allowed_users WHERE user_id=?", (user_id,))
        return cur.rowcount > 0


def get_all_allowed_users() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM allowed_users ORDER BY added_at ASC").fetchall()
        return [r["user_id"] for r in rows]


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def update_user_info(user_id: int, name: str, username: str):
    name = (name or "").strip()
    username = (username or "").strip()
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM allowed_users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            conn.execute("UPDATE allowed_users SET name=?, username=? WHERE user_id=?", (name, username, user_id))
        else:
            conn.execute("INSERT OR IGNORE INTO allowed_users (user_id, name, username) VALUES (?, ?, ?)", (user_id, name, username))


def is_user_paused(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT is_paused FROM allowed_users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["is_paused"] == 1)


def set_user_pause(user_id: int, is_paused: int):
    with get_conn() as conn:
        conn.execute("UPDATE allowed_users SET is_paused=? WHERE user_id=?", (is_paused, user_id))


def get_all_allowed_users_detailed() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id, name, username, is_paused, added_at FROM allowed_users ORDER BY added_at ASC").fetchall()
        return [dict(r) for r in rows]


def get_user_info(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT user_id, name, username, is_paused, added_at FROM allowed_users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_settings(user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
            return {"user_id": user_id, "auto_delete_24h": 1, "night_mode": 0, "speed_mode": "normal", "notify_finish": 1}
        return dict(row)


def update_user_setting(user_id: int, key: str, value: any):
    if key not in ("auto_delete_24h", "night_mode", "speed_mode", "notify_finish"):
        return
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
        conn.execute(f"UPDATE user_settings SET {key}=? WHERE user_id=?", (value, user_id))


def save_sent_message(user_id: int, session_name: str, chat_id: int, message_id: int):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO sent_messages (user_id, session_name, chat_id, message_id) VALUES (?, ?, ?, ?)",
                (user_id, session_name, chat_id, message_id)
            )
    except Exception:
        pass
def get_campaign_groups(campaign_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT g.* FROM groups g
               JOIN campaign_groups cg ON cg.group_id=g.id
               WHERE cg.campaign_id=?""",
            (campaign_id,),
        ).fetchall()


def get_due_campaigns() -> list[sqlite3.Row]:
    """next_run vaqti o'tgan yoki NULL bo'lgan aktiv kampaniyalar."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM campaigns
               WHERE is_active=1
               AND (next_run IS NULL OR next_run <= datetime('now'))
               ORDER BY next_run""",
        ).fetchall()


def log_send(campaign_id: int, account_id: int, group_id: int, status: str, error: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO send_log(campaign_id,account_id,group_id,status,error) VALUES(?,?,?,?,?)",
            (campaign_id, account_id, group_id, status, error),
        )


def get_statistics(user_id: int) -> dict:
    with get_conn() as conn:
        acc_total = conn.execute("SELECT COUNT(*) FROM accounts WHERE user_id=?", (user_id,)).fetchone()[0]
        acc_active = conn.execute("SELECT COUNT(*) FROM accounts WHERE user_id=? AND status='active'", (user_id,)).fetchone()[0]
        
        grp_total = conn.execute("SELECT COUNT(*) FROM groups WHERE user_id=?", (user_id,)).fetchone()[0]
        
        camp_total = conn.execute("SELECT COUNT(*) FROM campaigns WHERE user_id=?", (user_id,)).fetchone()[0]
        camp_active = conn.execute("SELECT COUNT(*) FROM campaigns WHERE user_id=? AND is_active=1", (user_id,)).fetchone()[0]
        
        sent_today = conn.execute("""
            SELECT COUNT(*) FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            WHERE c.user_id=? AND sl.status='sent' AND date(sl.sent_at) = date('now')
        """, (user_id,)).fetchone()[0]
        
        failed_today = conn.execute("""
            SELECT COUNT(*) FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            WHERE c.user_id=? AND sl.status='failed' AND date(sl.sent_at) = date('now')
        """, (user_id,)).fetchone()[0]
        
        sent_total = conn.execute("""
            SELECT COUNT(*) FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            WHERE c.user_id=? AND sl.status='sent'
        """, (user_id,)).fetchone()[0]
        
        failed_total = conn.execute("""
            SELECT COUNT(*) FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            WHERE c.user_id=? AND sl.status='failed'
        """, (user_id,)).fetchone()[0]
        
        errors = conn.execute("""
            SELECT sl.error, sl.sent_at, g.title, g.identifier
            FROM send_log sl
            JOIN campaigns c ON sl.campaign_id = c.id
            LEFT JOIN groups g ON sl.group_id = g.id
            WHERE c.user_id=? AND sl.status='failed' AND sl.error != ''
            ORDER BY sl.id DESC LIMIT 5
        """, (user_id,)).fetchall()
        
        error_list = []
        for r in errors:
            error_list.append({
                "error": r["error"],
                "sent_at": r["sent_at"],
                "group": r["title"] or r["identifier"] or "Noma'lum"
            })
            
        return {
            "acc_total": acc_total,
            "acc_active": acc_active,
            "grp_total": grp_total,
            "camp_total": camp_total,
            "camp_active": camp_active,
            "sent_today": sent_today,
            "failed_today": failed_today,
            "sent_total": sent_total,
            "failed_total": failed_total,
            "recent_errors": error_list
        }


# ── Allowed Users & Settings (Secret Admin Panel) ─────────────────────────────

def is_user_allowed(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM allowed_users WHERE user_id=?", (user_id,)).fetchone()
        return row is not None


def add_allowed_user(user_id: int) -> bool:
    try:
        with get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO allowed_users (user_id) VALUES (?)", (user_id,))
        return True
    except Exception:
        return False


def remove_allowed_user(user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM allowed_users WHERE user_id=?", (user_id,))
        return cur.rowcount > 0


def get_all_allowed_users() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM allowed_users ORDER BY added_at ASC").fetchall()
        return [r["user_id"] for r in rows]


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def update_user_info(user_id: int, name: str, username: str):
    name = (name or "").strip()
    username = (username or "").strip()
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM allowed_users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            conn.execute("UPDATE allowed_users SET name=?, username=? WHERE user_id=?", (name, username, user_id))
        else:
            conn.execute("INSERT OR IGNORE INTO allowed_users (user_id, name, username) VALUES (?, ?, ?)", (user_id, name, username))


def is_user_paused(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT is_paused FROM allowed_users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["is_paused"] == 1)


def set_user_pause(user_id: int, is_paused: int):
    with get_conn() as conn:
        conn.execute("UPDATE allowed_users SET is_paused=? WHERE user_id=?", (is_paused, user_id))


def get_all_allowed_users_detailed() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id, name, username, is_paused, added_at FROM allowed_users ORDER BY added_at ASC").fetchall()
        return [dict(r) for r in rows]


def get_user_info(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT user_id, name, username, is_paused, added_at FROM allowed_users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_settings(user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
            return {"user_id": user_id, "auto_delete_24h": 1, "night_mode": 0, "speed_mode": "normal", "notify_finish": 1}
        return dict(row)


def update_user_setting(user_id: int, key: str, value: any):
    if key not in ("auto_delete_24h", "night_mode", "speed_mode", "notify_finish"):
        return
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
        conn.execute(f"UPDATE user_settings SET {key}=? WHERE user_id=?", (value, user_id))


def save_sent_message(user_id: int, session_name: str, chat_id: int, message_id: int):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO sent_messages (user_id, session_name, chat_id, message_id) VALUES (?, ?, ?, ?)",
                (user_id, session_name, chat_id, message_id)
            )
    except Exception:
        pass


def get_old_sent_messages(hours: int = 24, limit: int = 500) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, user_id, session_name, chat_id, message_id, sent_at FROM sent_messages WHERE sent_at <= datetime('now', '-{hours} hours') LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_sent_messages_records(ids: list[int]):
    if not ids:
        return
    with get_conn() as conn:
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM sent_messages WHERE id IN ({placeholders})", ids)


def should_send_notification(user_id: int, error_type: str, target_id: int, cooldown_hours: int = 12) -> bool:
    """Tekshiradi: ushbu muammo (guruh/akkaunt) bo'yicha userga oxirgi cooldown_hours soat ichida xabar ketganmi?"""
    try:
        with get_conn() as conn:
            row = conn.execute(
                f"SELECT id FROM error_notifications WHERE user_id=? AND error_type=? AND target_id=? AND notified_at > datetime('now', '-{cooldown_hours} hours')",
                (user_id, error_type, target_id)
            ).fetchone()
            return row is None
    except Exception:
        return True


def record_notification(user_id: int, error_type: str, target_id: int):
    """Userga ogohlantirish xabari ketganini xotiraga yozib qo'yadi."""
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO error_notifications (user_id, error_type, target_id, notified_at) 
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(user_id, error_type, target_id) 
                   DO UPDATE SET notified_at=datetime('now')""",
                (user_id, error_type, target_id)
            )
    except Exception:
        pass


def remove_group_complete(group_id: int) -> bool:
    """Muammoli guruhni barcha kampaniyalardan va groups jadvalidan toza o'chirib tashlaydi."""
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM campaign_groups WHERE group_id=?", (group_id,))
            conn.execute("DELETE FROM groups WHERE id=?", (group_id,))
        return True
    except Exception:
        return False


def deactivate_account(account_id: int) -> bool:
    """Sessiyasi o'chgan/xato akkauntni inactive holatga o'tkazadi."""
    try:
        with get_conn() as conn:
            conn.execute("UPDATE accounts SET status='inactive' WHERE id=?", (account_id,))
        return True
    except Exception:
        return False


def get_log_and_db_stats() -> dict:
    """Serverdagi log fayllari, DB hajmi va eski yozuvlar statistikasini qaytaradi."""
    import os
    stats = {}
    
    # 1. DB hajmi va yozuvlar soni
    db_path = getattr(config, "DB_PATH", "taxibot.db")
    stats["db_size_mb"] = round(os.path.getsize(db_path) / (1024 * 1024), 2) if os.path.exists(db_path) else 0.0
    
    try:
        with get_conn() as conn:
            sent_count = conn.execute("SELECT COUNT(*) FROM sent_messages").fetchone()[0]
            err_count = conn.execute("SELECT COUNT(*) FROM error_notifications").fetchone()[0]
    except Exception:
        sent_count, err_count = 0, 0
        
    stats["sent_messages_count"] = sent_count
    stats["error_notifications_count"] = err_count

    # 2. Log fayl hajmi
    log_files = ["data/bot.log", "bot.log", "taxibot.log", "app.log", "/home/nabiyev/assistant_taxist/assistent_bot/taxibot/data/bot.log"]
    total_log_bytes = 0
    found_logs = []
    seen = set()
    for lf in log_files:
        if os.path.exists(lf):
            abs_p = os.path.abspath(lf)
            if abs_p in seen:
                continue
            seen.add(abs_p)
            sz = os.path.getsize(lf)
            total_log_bytes += sz
            found_logs.append(f"{os.path.basename(lf)} ({round(sz / 1024, 1)} KB)")
            
    stats["total_log_mb"] = round(total_log_bytes / (1024 * 1024), 2)
    stats["found_logs_str"] = ", ".join(found_logs) if found_logs else "Log fayl topilmadi (0 KB)"
    return stats


def clean_server_logs(delete_sent_hours: int = 48) -> dict:
    """Serverdagi log fayllarni va eskirgan DB yozuvlarini tozalaydi (Sessiyalarga va asosiy bazalarga TEGMASDAN!)."""
    import os
    from datetime import datetime
    cleaned_bytes = 0
    log_files = ["data/bot.log", "bot.log", "taxibot.log", "app.log", "/home/nabiyev/assistant_taxist/assistent_bot/taxibot/data/bot.log"]
    seen = set()
    for lf in log_files:
        if os.path.exists(lf):
            abs_p = os.path.abspath(lf)
            if abs_p in seen:
                continue
            seen.add(abs_p)
            try:
                sz = os.path.getsize(lf)
                with open(lf, "w", encoding="utf-8") as f:
                    f.write(f"# Log tozalandi - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
                cleaned_bytes += sz
            except Exception:
                pass

    del_rows = 0
    try:
        with get_conn() as conn:
            cur1 = conn.execute(f"DELETE FROM sent_messages WHERE sent_at <= datetime('now', '-{delete_sent_hours} hours')")
            del_rows += cur1.rowcount if cur1.rowcount > 0 else 0
            cur2 = conn.execute("DELETE FROM error_notifications WHERE notified_at <= datetime('now', '-48 hours')")
            del_rows += cur2.rowcount if cur2.rowcount > 0 else 0
            try:
                conn.execute("VACUUM")
            except Exception:
                pass
    except Exception:
        pass

    return {
        "cleaned_mb": round(cleaned_bytes / (1024 * 1024), 2),
        "deleted_db_rows": del_rows
    }
