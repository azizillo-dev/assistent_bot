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
            user_id  INTEGER PRIMARY KEY,
            added_at TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)

    # Eski DB uchun yangi ustunlarni qo'shish (migration)
    with get_conn() as conn:
        try:
            conn.execute("ALTER TABLE campaigns ADD COLUMN acc_interval_s INTEGER NOT NULL DEFAULT 2")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE campaigns ADD COLUMN font_style TEXT NOT NULL DEFAULT 'none'")
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
        acc_active = conn.execute("SELECT COUNT(*) FROM accounts WHERE user_id=? AND is_active=1", (user_id,)).fetchone()[0]
        
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

