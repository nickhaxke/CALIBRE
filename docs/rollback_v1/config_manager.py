#!/usr/bin/env python3
"""
Institutional Configuration Manager (SQLite-backed)
Aethelgard Institute of Technology - Calibre Institutional Digital Library

Responsibilities:
1. Versioned SQLite schema management with automated migrations and transactional execution.
2. Runtime location resolution (AppData / Local Dev Override via CALIBRE_INSTITUTIONAL_CONFIG_DIR).
3. Institution identity, library mappings, system settings, and institutional user profile management.
4. Immutable audit logging of administrative changes.
5. Automatic database backups before schema changes.
"""

import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


class ClosingConnection(sqlite3.Connection):
    """Commit/rollback and release the Windows file handle at the end of a scope."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()

def get_config_directory():
    """Resolves the configuration directory according to institutional hierarchy:
    1. Environment override: CALIBRE_INSTITUTIONAL_CONFIG_DIR
    2. Production standard: %LOCALAPPDATA%/CalibreInstitutional/config
    3. Fallback: ~/.calibre-institutional/config
    """
    env_dir = os.environ.get("CALIBRE_INSTITUTIONAL_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    # Production Windows LocalAppData
    localappdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if localappdata:
        p = Path(localappdata) / "CalibreInstitutional" / "config"
    else:
        p = Path.home() / ".calibre-institutional" / "config"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)

def get_db_path():
    cfg_dir = get_config_directory()
    return os.path.join(cfg_dir, "institutional_config.sqlite")

class ConfigManager:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()
        self.ensure_schema()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def create_backup(self):
        return self.backup_database()

    def backup_database(self):
        """Creates a timestamped snapshot of the configuration database."""
        if not os.path.exists(self.db_path):
            return None
        backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"institutional_config_{ts}.sqlite.bak")
        shutil.copy2(self.db_path, backup_path)
        return backup_path

    def ensure_schema(self):
        """Initializes tables, migration tracking, and applies migrations transactionally."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """)
            cur = conn.cursor()
            cur.execute("SELECT MAX(version) FROM schema_migrations")
            row = cur.fetchone()
            current_version = row[0] if (row and row[0] is not None) else 0

            if current_version < 1:
                self._apply_migration_v1(conn)

    def _apply_migration_v1(self, conn):
        """Initial v1 Schema: Institution Settings, Libraries, System Config, Roles, and Audit Log."""
        conn.executescript("""
            -- 1. Institution Identity & Branding Settings
            CREATE TABLE IF NOT EXISTS institution_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                institution_name TEXT NOT NULL,
                short_name TEXT NOT NULL,
                logo_path TEXT,
                library_title TEXT NOT NULL,
                motto TEXT,
                contact_email TEXT,
                contact_phone TEXT,
                default_language TEXT DEFAULT 'en',
                primary_color TEXT DEFAULT '#0f172a',
                accent_color TEXT DEFAULT '#2563eb',
                accent_gold TEXT DEFAULT '#d97706',
                updated_at TEXT NOT NULL
            );

            -- 2. Connected Calibre Libraries
            CREATE TABLE IF NOT EXISTS libraries (
                library_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                access_policy TEXT NOT NULL DEFAULT 'public',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- 3. System Configuration Flags
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- 4. Institutional User Role Profiles (Joined with Calibre accounts)
            CREATE TABLE IF NOT EXISTS institutional_user_profiles (
                username TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                display_name TEXT NOT NULL,
                department TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- 5. Immutable Audit Log
            CREATE TABLE IF NOT EXISTS audit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT
            );
        """)

        # Seed defaults if not populated
        now = datetime.now(timezone.utc).isoformat()
        
        # Check institution_settings
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM institution_settings WHERE id = 1")
        if cur.fetchone()[0] == 0:
            conn.execute("""
                INSERT INTO institution_settings (
                    id, institution_name, short_name, logo_path, library_title,
                    motto, contact_email, contact_phone, default_language,
                    primary_color, accent_color, accent_gold, updated_at
                ) VALUES (
                    1, 'Aethelgard Institute of Technology', 'AIT', '',
                    'Institutional Digital Library & Research Repository',
                    'Knowledge Preserved, Universally Accessible',
                    'library@aethelgard.edu', '+1 (555) 019-8841', 'en',
                    '#0f172a', '#2563eb', '#d97706', ?
                )
            """, (now,))

        # Check system_config
        default_setup_completed = "0"
        defaults = {
            "setup_completed": default_setup_completed,
            "schema_version": "1",
            "gateway_port": "8085",
            "backend_port": "8088",
            "calibre_bin_dir": r"C:/Program Files/Calibre2",
            "user_db_path": os.path.join(os.path.dirname(self.db_path), "server-users.sqlite"),
            "dev_mode": "1"
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO system_config (key, value, updated_at) VALUES (?, ?, ?)", (k, v, now))

        conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)", (now,))

    # --------------------------------------------------------------------------
    # Institution Settings API
    # --------------------------------------------------------------------------
    def get_institution_settings(self):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM institution_settings WHERE id = 1")
            row = cur.fetchone()
            if not row:
                return {}
            result = dict(row)
            result.update(name=result['institution_name'], library_name=result['library_title'], logo_url=result.get('logo_path', ''))
            return result

    def update_institution_settings(self, name=None, short_name=None, library_title=None, motto=None,
                                    contact_email=None, contact_phone=None, logo_path=None,
                                    primary_color=None, accent_color=None, accent_gold=None,
                                    actor="SYSTEM", institution_name=None, library_name=None, logo_url=None):
        name = name or institution_name
        library_title = library_title or library_name
        logo_path = logo_path or logo_url
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM institution_settings WHERE id = 1")
            row = cur.fetchone()
            old = dict(row) if row else {}

            conn.execute("""
                UPDATE institution_settings SET
                    institution_name = coalesce(?, institution_name),
                    short_name = coalesce(?, short_name),
                    library_title = coalesce(?, library_title),
                    motto = coalesce(?, motto),
                    contact_email = coalesce(?, contact_email),
                    contact_phone = coalesce(?, contact_phone),
                    logo_path = coalesce(?, logo_path),
                    primary_color = coalesce(?, primary_color),
                    accent_color = coalesce(?, accent_color),
                    accent_gold = coalesce(?, accent_gold),
                    updated_at = ?
                WHERE id = 1
            """, (name, short_name, library_title, motto, contact_email, contact_phone,
                  logo_path, primary_color, accent_color, accent_gold, now))

            # Audit record
            self.log_audit(actor, "INSTITUTION_SETTINGS_UPDATED", json.dumps({
                "institution_name": name,
                "short_name": short_name,
                "library_title": library_title
            }), conn=conn)
        return True

    # --------------------------------------------------------------------------
    # Library Configuration API
    # --------------------------------------------------------------------------
    def get_libraries(self):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM libraries ORDER BY is_default DESC, display_name ASC")
            res = []
            for r in cur.fetchall():
                d = dict(r)
                d['id'] = d['library_id']
                res.append(d)
            return res

    def get_active_libraries(self):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM libraries WHERE is_active = 1 ORDER BY is_default DESC, display_name ASC")
            return [dict(r) for r in cur.fetchall()]

    def get_library(self, library_id):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM libraries WHERE library_id = ?", (library_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def add_library(self, display_name=None, path=None, is_active=True, is_default=False, access_policy="public", actor="SYSTEM", library_path=None, name=None):
        display_name = display_name or name or (os.path.basename(path) if path else "Calibre Library")
        path = path or library_path
        path = os.path.abspath(path.strip())
        base_id = Path(path).name.lower().replace(" ", "_")
        now = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT library_id FROM libraries WHERE path = ?", (path,))
            existing = cur.fetchone()
            if existing:
                if is_default:
                    cur.execute("UPDATE libraries SET is_default = 0")
                cur.execute(
                    "UPDATE libraries SET display_name = ?, is_active = ?, is_default = CASE WHEN ? THEN 1 ELSE is_default END, updated_at = ? WHERE library_id = ?",
                    (display_name, 1 if is_active else 0, 1 if is_default else 0, now, existing[0])
                )
                self.log_audit(actor, "LIBRARY_UPDATED", json.dumps({"library_id": existing[0], "path": path}), conn=conn)
                return existing[0]

            library_id = base_id
            counter = 1
            while True:
                cur.execute("SELECT library_id FROM libraries WHERE library_id = ?", (library_id,))
                if not cur.fetchone():
                    break
                counter += 1
                library_id = f"{base_id}_{counter}"

            if is_default:
                conn.execute("UPDATE libraries SET is_default = 0")
            conn.execute("""
                INSERT INTO libraries (library_id, display_name, path, is_active, is_default, access_policy, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (library_id, display_name, path, 1 if is_active else 0, 1 if is_default else 0, access_policy, now, now))

            self.log_audit(actor, "LIBRARY_ADDED", json.dumps({"library_id": library_id, "path": path, "display_name": display_name}), conn=conn)
        return self.get_library(library_id)

    def update_library(self, library_id, display_name=None, is_active=None, is_default=None, access_policy=None, actor="SYSTEM"):
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            if is_default:
                conn.execute("UPDATE libraries SET is_default = 0")

            params = []
            updates = []
            if display_name is not None:
                updates.append("display_name = ?")
                params.append(display_name)
            if is_active is not None:
                updates.append("is_active = ?")
                params.append(1 if is_active else 0)
            if is_default is not None:
                updates.append("is_default = ?")
                params.append(1 if is_default else 0)
            if access_policy is not None:
                updates.append("access_policy = ?")
                params.append(access_policy)

            updates.append("updated_at = ?")
            params.append(now)
            params.append(library_id)

            conn.execute(f"UPDATE libraries SET {', '.join(updates)} WHERE library_id = ?", params)
            self.log_audit(actor, "LIBRARY_UPDATED", json.dumps({"library_id": library_id, "display_name": display_name, "is_active": is_active}), conn=conn)
        return True

    def remove_library(self, library_id, actor="SYSTEM"):
        """Disables/removes library registration from the catalog without deleting disk files."""
        with self.get_connection() as conn:
            lib = self.get_library(library_id)
            if not lib:
                return False
            conn.execute("DELETE FROM libraries WHERE library_id = ?", (library_id,))
            self.log_audit(actor, "LIBRARY_REMOVED", json.dumps({"library_id": library_id, "path": lib["path"]}), conn=conn)
        return True

    # --------------------------------------------------------------------------
    # System Configuration API
    # --------------------------------------------------------------------------
    def get_system_config(self):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM system_config")
            return {r["key"]: r["value"] for r in cur.fetchall()}

    def get_config_value(self, key, default=None):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM system_config WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def set_config_value(self, key, value, actor="SYSTEM"):
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO system_config (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (str(key), str(value), now))
            self.log_audit(actor, "SYSTEM_CONFIG_UPDATED", json.dumps({key: str(value)}), conn=conn)
        return True

    def is_setup_completed(self):
        return self.get_config_value("setup_completed", "0") == "1"

    def mark_setup_completed(self, completed=True, actor="SYSTEM"):
        val = "1" if completed else "0"
        self.set_config_value("setup_completed", val, actor=actor)
        self.log_audit(actor, "SETUP_COMPLETION_STATE_CHANGED", json.dumps({"setup_completed": val}))
        return True

    def set_setup_completed(self, completed=True, actor="SYSTEM"):
        """Convenience alias for mark_setup_completed."""
        return self.mark_setup_completed(completed=completed, actor=actor)

    # --------------------------------------------------------------------------
    # Institutional User Role Profile API
    # --------------------------------------------------------------------------
    def get_user_profile(self, username):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM institutional_user_profiles WHERE username = ?", (username.strip(),))
            row = cur.fetchone()
            if row:
                return dict(row)
            # Default fallback for unprofiled user
            return {
                "username": username,
                "role": "Student",
                "display_name": username,
                "department": "Campus Patron"
            }

    def get_all_user_profiles(self):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM institutional_user_profiles ORDER BY username ASC")
            return {r["username"]: dict(r) for r in cur.fetchall()}

    def set_user_profile(self, username, role, display_name, department=None, actor="SYSTEM"):
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO institutional_user_profiles (username, role, display_name, department, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    role = excluded.role,
                    display_name = excluded.display_name,
                    department = excluded.department,
                    updated_at = excluded.updated_at
            """, (username.strip(), role, display_name, department, now, now))
            self.log_audit(actor, "USER_PROFILE_UPDATED", json.dumps({"username": username, "role": role, "display_name": display_name}), conn=conn)
        return True

    def delete_user_profile(self, username, actor="SYSTEM"):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM institutional_user_profiles WHERE username = ?", (username.strip(),))
            self.log_audit(actor, "USER_PROFILE_DELETED", json.dumps({"username": username}), conn=conn)
        return True

    # --------------------------------------------------------------------------
    # Immutable Audit Log API
    # --------------------------------------------------------------------------
    def log_audit(self, actor, action, details=None, conn=None):
        now = datetime.now(timezone.utc).isoformat()
        if conn is not None:
            conn.execute("""
                INSERT INTO audit_records (timestamp, actor, action, details)
                VALUES (?, ?, ?, ?)
            """, (now, str(actor), str(action), str(details) if details else None))
            return True
        with self.get_connection() as c:
            c.execute("""
                INSERT INTO audit_records (timestamp, actor, action, details)
                VALUES (?, ?, ?, ?)
            """, (now, str(actor), str(action), str(details) if details else None))
        return True

    def get_audit_log(self, limit=50):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_records ORDER BY id DESC LIMIT ?", (int(limit),))
            return [dict(r) for r in cur.fetchall()]

# Global Singleton Instance
_GLOBAL_CONFIG_MANAGER = None

def get_config_manager():
    global _GLOBAL_CONFIG_MANAGER
    if _GLOBAL_CONFIG_MANAGER is None:
        _GLOBAL_CONFIG_MANAGER = ConfigManager()
    return _GLOBAL_CONFIG_MANAGER
