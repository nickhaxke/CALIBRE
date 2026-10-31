#!/usr/bin/env python3
"""
Institutional Configuration Manager (SQLite-backed)
Aethelgard Institute of Technology - Calibre Institutional Digital Library

Responsibilities:
1. Versioned SQLite schema management with automated migrations and transactional execution.
2. Runtime location resolution (AppData / Local Dev Override via CALIBRE_INSTITUTIONAL_CONFIG_DIR).
3. Institution identity, library mappings, system settings, catalogue settings, and institutional user profile management.
4. Per-library role & user access control evaluation.
5. Three-tier separated backup, verification, and safe restore (Tier 1 Config, Tier 2 Auth, Tier 3 Complete Library Archive).
6. Immutable audit logging with search filtering and pagination.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
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


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class ConfigManager:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()
        self.ensure_schema()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def get_backups_directory(self) -> str:
        bdir = os.path.join(os.path.dirname(self.db_path), "backups")
        os.makedirs(bdir, exist_ok=True)
        return bdir

    def get_branding_directory(self) -> str:
        brdir = os.path.join(os.path.dirname(self.db_path), "branding")
        os.makedirs(brdir, exist_ok=True)
        return brdir

    def create_backup(self):
        return self.backup_database()

    def backup_database(self, actor="SYSTEM"):
        """Creates a timestamped Tier-1 snapshot of the configuration database using SQLite online backup."""
        if not os.path.exists(self.db_path):
            return None
        backup_dir = self.get_backups_directory()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:19]
        backup_path = os.path.join(backup_dir, f"institutional_config_{ts}.sqlite.bak")
        with self.get_connection() as src_conn:
            dst_conn = sqlite3.connect(backup_path)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
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

            # Ensure V2 columns on institutional_user_profiles (non-destructive upgrade)
            cur.execute("PRAGMA table_info(institutional_user_profiles)")
            existing_cols = {r[1] for r in cur.fetchall()}
            if "is_active" not in existing_cols:
                conn.execute("ALTER TABLE institutional_user_profiles ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
            if "allowed_libraries" not in existing_cols:
                conn.execute("ALTER TABLE institutional_user_profiles ADD COLUMN allowed_libraries TEXT NOT NULL DEFAULT '*'")

            # Ensure V2 catalogue defaults exist in system_config
            now = datetime.now(timezone.utc).isoformat()
            cat_defaults = {
                "catalogue_page_size": "24",
                "catalogue_default_sort": "title_asc",
                "catalogue_facets": "tags,authors,series,publisher,formats,languages",
                "catalogue_inject_bar": "1",
                "catalogue_inbrowser_reader": "1",
                "catalogue_download_policy": "authenticated",
            }
            for k, v in cat_defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO system_config (key, value, updated_at) VALUES (?, ?, ?)",
                    (k, v, now)
                )

            # Ensure at least one active library is marked as default if libraries exist
            cur.execute("SELECT COUNT(*) FROM libraries WHERE is_default = 1")
            if (cur.fetchone()[0] or 0) == 0:
                cur.execute("SELECT library_id FROM libraries WHERE is_active = 1 ORDER BY created_at ASC LIMIT 1")
                first_lib = cur.fetchone()
                if first_lib:
                    conn.execute("UPDATE libraries SET is_default = 1 WHERE library_id = ?", (first_lib[0],))

            # Normalize stale bootstrap template admin display name if institution was customized
            cur.execute("SELECT institution_name FROM institution_settings WHERE id = 1")
            inst_row = cur.fetchone()
            if inst_row and inst_row[0] and inst_row[0] != "Aethelgard Institute of Technology":
                conn.execute(
                    """UPDATE institutional_user_profiles
                       SET display_name = ?, updated_at = ?
                       WHERE role = 'Administrator'
                         AND display_name = 'Aethelgard Institute of Technology Administrator'""",
                    (f"{inst_row[0]} Administrator", now)
                )

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
                primary_color TEXT DEFAULT '#183c34',
                accent_color TEXT DEFAULT '#2563eb',
                accent_gold TEXT DEFAULT '#b89554',
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
                is_active INTEGER NOT NULL DEFAULT 1,
                allowed_libraries TEXT NOT NULL DEFAULT '*',
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

        now = datetime.now(timezone.utc).isoformat()
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
                    '#183c34', '#2563eb', '#b89554', ?
                )
            """, (now,))

        defaults = {
            "setup_completed": "0",
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
            result.update(
                name=result["institution_name"],
                library_name=result["library_title"],
                logo_url=result.get("logo_path", "")
            )
            return result

    def update_institution_settings(self, name=None, short_name=None, library_title=None, motto=None,
                                    contact_email=None, contact_phone=None, logo_path=None,
                                    primary_color=None, accent_color=None, accent_gold=None,
                                    actor="SYSTEM", institution_name=None, library_name=None, logo_url=None):
        name = name if name is not None else institution_name
        library_title = library_title if library_title is not None else library_name
        logo_path = logo_path if logo_path is not None else logo_url
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT institution_name FROM institution_settings WHERE id = 1")
            prev_row = cur.fetchone()
            prev_name = prev_row[0] if prev_row else None

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

            if name and name.strip():
                clean_name = name.strip()
                stale_titles = {"Aethelgard Institute of Technology Administrator"}
                if prev_name:
                    stale_titles.add(f"{prev_name} Administrator")
                for old_title in stale_titles:
                    conn.execute(
                        """UPDATE institutional_user_profiles
                           SET display_name = ?, updated_at = ?
                           WHERE role = 'Administrator' AND display_name = ?""",
                        (f"{clean_name} Administrator", now, old_title)
                    )

            self.log_audit(actor, "INSTITUTION_SETTINGS_UPDATED", json.dumps({
                "institution_name": name,
                "short_name": short_name,
                "library_title": library_title,
                "primary_color": primary_color,
                "logo_path": logo_path
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
                d["id"] = d["library_id"]
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
            if row:
                d = dict(row)
                d["id"] = d["library_id"]
                return d
            return None

    def add_library(self, display_name=None, path=None, is_active=True, is_default=False, access_policy="public", actor="SYSTEM", library_path=None, name=None):
        path = path or library_path
        path = os.path.abspath(path.strip())
        display_name = display_name or name or (os.path.basename(path) if path else "Calibre Library")
        base_id = Path(path).name.lower().replace(" ", "_").replace("-", "_")
        now = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT library_id FROM libraries WHERE lower(path) = lower(?)", (path,))
            existing = cur.fetchone()
            if existing:
                lib_id = existing[0]
                if is_default:
                    cur.execute("UPDATE libraries SET is_default = 0")
                cur.execute(
                    """UPDATE libraries
                       SET display_name = ?, is_active = ?, access_policy = coalesce(?, access_policy),
                           is_default = CASE WHEN ? THEN 1 ELSE is_default END, updated_at = ?
                       WHERE library_id = ?""",
                    (display_name, 1 if is_active else 0, access_policy, 1 if is_default else 0, now, lib_id)
                )
                self.log_audit(actor, "LIBRARY_UPDATED", json.dumps({"library_id": lib_id, "path": path, "access_policy": access_policy}), conn=conn)
                return self.get_library(lib_id)

            library_id = base_id or "library"
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

            self.log_audit(actor, "LIBRARY_ADDED", json.dumps({
                "library_id": library_id, "path": path, "display_name": display_name, "access_policy": access_policy
            }), conn=conn)
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
            self.log_audit(actor, "LIBRARY_UPDATED", json.dumps({
                "library_id": library_id, "display_name": display_name, "is_active": is_active,
                "is_default": is_default, "access_policy": access_policy
            }), conn=conn)
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
    # System & Catalogue Configuration API
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

    def get_landing_page_content(self):
        cfg = self.get_system_config()
        return {
            "hero_eyebrow": cfg.get("landing_hero_eyebrow", "A HOME FOR CURIOUS MINDS"),
            "hero_title": cfg.get("landing_hero_title", "Great ideas begin with an open book."),
            "hero_description": cfg.get("landing_hero_description", "Discover academic works, explore new perspectives, and make room for your next breakthrough. Your institutional collection, wherever you learn."),
            "cta_label": cfg.get("landing_cta_label", "Explore the library ↗"),
            "about_heading": cfg.get("landing_about_heading", "A collection that moves you forward."),
            "about_description": cfg.get("landing_about_description", "From foundational texts to fresh thinking, find the resources that support your studies, teaching, and research."),
            "footer_text": cfg.get("landing_footer_text", "Powered by Calibre · Built for our community"),
            "hero_image_url": cfg.get("landing_hero_image_url", ""),
            "about_image_url": cfg.get("landing_about_image_url", "")
        }

    def update_landing_page_content(self, data: dict, actor="SYSTEM"):
        now = datetime.now(timezone.utc).isoformat()
        allowed_keys = {
            "hero_eyebrow": "landing_hero_eyebrow",
            "hero_title": "landing_hero_title",
            "hero_description": "landing_hero_description",
            "cta_label": "landing_cta_label",
            "about_heading": "landing_about_heading",
            "about_description": "landing_about_description",
            "footer_text": "landing_footer_text",
            "hero_image_url": "landing_hero_image_url",
            "about_image_url": "landing_about_image_url"
        }
        updates = {}
        for k, sys_k in allowed_keys.items():
            if k in data and data[k] is not None:
                updates[sys_k] = str(data[k]).strip()
        with self.get_connection() as conn:
            for sys_k, val in updates.items():
                conn.execute("""
                    INSERT INTO system_config (key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """, (sys_k, val, now))
            self.log_audit(actor, "LANDING_PAGE_CONTENT_UPDATED", json.dumps(updates), conn=conn)
        return self.get_landing_page_content()

    def reset_landing_page_content(self, actor="SYSTEM"):
        now = datetime.now(timezone.utc).isoformat()
        keys_to_clear = [
            "landing_hero_eyebrow", "landing_hero_title", "landing_hero_description",
            "landing_cta_label", "landing_about_heading", "landing_about_description",
            "landing_footer_text", "landing_hero_image_url", "landing_about_image_url"
        ]
        with self.get_connection() as conn:
            for k in keys_to_clear:
                conn.execute("DELETE FROM system_config WHERE key = ?", (k,))
            self.log_audit(actor, "LANDING_PAGE_CONTENT_RESET", "{}", conn=conn)
        return self.get_landing_page_content()

    def get_catalogue_settings(self):
        cfg = self.get_system_config()
        facets_raw = cfg.get("catalogue_facets", "tags,authors,series,publisher,formats,languages")
        facets = [f.strip() for f in facets_raw.split(",") if f.strip()]
        return {
            "page_size": int(cfg.get("catalogue_page_size", "24") or 24),
            "default_sort": cfg.get("catalogue_default_sort", "title_asc"),
            "facets": facets,
            "exposed_facets": facets,
            "inject_bar": cfg.get("catalogue_inject_bar", "1") == "1",
            "inbrowser_reader": cfg.get("catalogue_inbrowser_reader", "1") == "1",
            "download_policy": cfg.get("catalogue_download_policy", "authenticated")
        }

    def update_catalogue_settings(self, page_size=None, default_sort=None, facets=None,
                                  inject_bar=None, inbrowser_reader=None, download_policy=None,
                                  actor="SYSTEM", exposed_facets=None):
        now = datetime.now(timezone.utc).isoformat()
        current = self.get_catalogue_settings()
        if facets is None and exposed_facets is not None:
            facets = exposed_facets
        if isinstance(facets, list):
            facets_str = ",".join(str(f).strip() for f in facets if str(f).strip())
        elif isinstance(facets, str):
            facets_str = facets
        else:
            facets_str = ",".join(current.get("facets", ["tags", "authors", "series", "publisher", "formats", "languages"]))

        eff_page_size = page_size if page_size is not None else current.get("page_size", 24)
        eff_sort = default_sort if default_sort is not None else current.get("default_sort", "title_asc")
        eff_inject = inject_bar if inject_bar is not None else current.get("inject_bar", True)
        eff_reader = inbrowser_reader if inbrowser_reader is not None else current.get("inbrowser_reader", True)
        eff_dl = download_policy if download_policy is not None else current.get("download_policy", "authenticated")

        updates = {
            "catalogue_page_size": str(max(1, min(120, int(eff_page_size or 24)))),
            "catalogue_default_sort": str(eff_sort or "title_asc"),
            "catalogue_facets": facets_str,
            "catalogue_inject_bar": "1" if eff_inject else "0",
            "catalogue_inbrowser_reader": "1" if eff_reader else "0",
            "catalogue_download_policy": str(eff_dl or "authenticated"),
        }
        with self.get_connection() as conn:
            for k, v in updates.items():
                conn.execute("""
                    INSERT INTO system_config (key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """, (k, v, now))
            self.log_audit(actor, "CATALOGUE_SETTINGS_UPDATED", json.dumps(updates), conn=conn)
        return self.get_catalogue_settings()

    def is_setup_completed(self):
        return self.get_config_value("setup_completed", "0") == "1"

    def mark_setup_completed(self, completed=True, actor="SYSTEM"):
        val = "1" if completed else "0"
        self.set_config_value("setup_completed", val, actor=actor)
        self.log_audit(actor, "SETUP_COMPLETION_STATE_CHANGED", json.dumps({"setup_completed": val}))
        return True

    def set_setup_completed(self, completed=True, actor="SYSTEM"):
        return self.mark_setup_completed(completed=completed, actor=actor)

    # --------------------------------------------------------------------------
    # Institutional User Role Profile & Backend Access Policy API
    # --------------------------------------------------------------------------
    def get_user_profile(self, username):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM institutional_user_profiles WHERE username = ?", (username.strip(),))
            row = cur.fetchone()
            if row:
                d = dict(row)
                d["is_active"] = bool(d.get("is_active", 1))
                d["allowed_libraries"] = d.get("allowed_libraries") or "*"
                return d
            return {
                "username": username,
                "role": "Student",
                "display_name": username,
                "department": "Campus Patron",
                "is_active": True,
                "allowed_libraries": "*"
            }

    def get_all_user_profiles(self):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM institutional_user_profiles ORDER BY username ASC")
            out = {}
            for r in cur.fetchall():
                d = dict(r)
                d["is_active"] = bool(d.get("is_active", 1))
                d["allowed_libraries"] = d.get("allowed_libraries") or "*"
                out[d["username"]] = d
            return out

    def set_user_profile(self, username, role, display_name, department=None, is_active=None, allowed_libraries=None, actor="SYSTEM"):
        username = username.strip()
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT is_active, allowed_libraries FROM institutional_user_profiles WHERE username = ?", (username,))
            existing = cur.fetchone()
            act_val = (1 if is_active else 0) if is_active is not None else (existing["is_active"] if existing else 1)
            if isinstance(allowed_libraries, list):
                libs_val = ",".join(str(x).strip() for x in allowed_libraries if str(x).strip()) or "*"
            elif allowed_libraries is not None:
                libs_val = str(allowed_libraries).strip() or "*"
            else:
                libs_val = existing["allowed_libraries"] if existing else "*"

            conn.execute("""
                INSERT INTO institutional_user_profiles (
                    username, role, display_name, department, is_active, allowed_libraries, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    role = excluded.role,
                    display_name = excluded.display_name,
                    department = excluded.department,
                    is_active = excluded.is_active,
                    allowed_libraries = excluded.allowed_libraries,
                    updated_at = excluded.updated_at
            """, (username, role, display_name, department, act_val, libs_val, now, now))
            self.log_audit(actor, "USER_PROFILE_UPDATED", json.dumps({
                "username": username, "role": role, "display_name": display_name,
                "is_active": bool(act_val), "allowed_libraries": libs_val
            }), conn=conn)
        return True

    def set_user_active(self, username, is_active: bool, actor="SYSTEM"):
        prof = self.get_user_profile(username)
        self.set_user_profile(
            username=username,
            role=prof.get("role", "Patron"),
            display_name=prof.get("display_name", username),
            department=prof.get("department", ""),
            is_active=bool(is_active),
            allowed_libraries=prof.get("allowed_libraries", "*"),
            actor=actor
        )
        self.log_audit(actor, "USER_ACTIVE_STATE_CHANGED", json.dumps({"username": username, "is_active": bool(is_active)}))
        return True

    def delete_user_profile(self, username, actor="SYSTEM"):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM institutional_user_profiles WHERE username = ?", (username.strip(),))
            self.log_audit(actor, "USER_PROFILE_DELETED", json.dumps({"username": username}), conn=conn)
        return True

    def _resolve_library_record(self, library_identifier: str):
        """Matches a library by library_id or by Calibre server_library_id (folder basename)."""
        if not library_identifier:
            libs = self.get_active_libraries()
            return libs[0] if libs else None
        norm_req = library_identifier.strip().lower().replace(" ", "_").replace("-", "_")
        for lib in self.get_libraries():
            lid = (lib.get("library_id") or "").lower().replace("-", "_")
            bname = os.path.basename(lib.get("path", "")).lower().replace(" ", "_").replace("-", "_")
            if norm_req in (lid, bname, (lib.get("library_id") or "").lower()):
                return lib
        return None

    def is_user_allowed_library(self, username: str, role: str, library_identifier: str = "") -> bool:
        """Evaluates backend authorization for a user accessing a specific Calibre library."""
        prof = self.get_user_profile(username)
        if not prof.get("is_active", True):
            return False
        effective_role = role or prof.get("role", "Patron")
        if effective_role == "Administrator":
            return True

        lib = self._resolve_library_record(library_identifier)
        if not lib:
            # If no libraries are registered or default library is queried, check general access
            return True
        if not lib.get("is_active", 1):
            return False

        lib_id = lib["library_id"]
        allowed_spec = (prof.get("allowed_libraries") or "*").strip()
        if allowed_spec and allowed_spec != "*":
            allowed_set = {x.strip().lower().replace("-", "_") for x in allowed_spec.split(",") if x.strip()}
            bname = os.path.basename(lib.get("path", "")).lower().replace(" ", "_").replace("-", "_")
            return (lib_id.lower().replace("-", "_") in allowed_set) or (bname in allowed_set)

        policy = (lib.get("access_policy") or "public").lower()
        if policy == "public":
            return True
        if policy in ("institutional", "campus_only"):
            return effective_role in ("Student", "Staff", "Faculty", "Administrator")
        if policy == "faculty_only":
            return effective_role in ("Faculty", "Staff", "Administrator")
        if policy in ("admin_only", "restricted"):
            return effective_role == "Administrator"
        return True

    # --------------------------------------------------------------------------
    # Three-Tier Backup, Verification & Safe Restore API
    # --------------------------------------------------------------------------
    def create_tier_backup(self, tier: str, userdb_path: str = None, library_id: str = None, actor: str = "SYSTEM") -> dict:
        backup_dir = self.get_backups_directory()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        if tier == "config":
            bp = self.backup_database(actor=actor)
            self.log_audit(actor, "BACKUP_TIER1_CONFIG_CREATED", json.dumps({"backup_path": bp, "tier": "config"}))
            return {
                "success": True,
                "tier": "config",
                "tier_label": "Tier 1 · Institutional Configuration",
                "backup_path": bp,
                "filename": os.path.basename(bp),
                "sha256": sha256_file(bp)
            }

        if tier == "auth":
            if not userdb_path:
                userdb_path = os.path.join(os.path.dirname(self.db_path), "server-users.sqlite")
            dst_db = os.path.join(backup_dir, f"server-users_{ts}.sqlite.bak")
            if os.path.isfile(userdb_path):
                src_conn = sqlite3.connect(f"file:{userdb_path}?mode=ro", uri=True, timeout=5.0)
                dst_conn = sqlite3.connect(dst_db)
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()
                    src_conn.close()
            else:
                # Initialize valid empty users table if userdb does not exist yet
                dst_conn = sqlite3.connect(dst_db)
                dst_conn.execute("CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, pw TEXT, timestamp TEXT, session_data TEXT, readonly TEXT, misc TEXT)")
                dst_conn.commit()
                dst_conn.close()

            profiles_sidecar = dst_db + ".profiles.json"
            with open(profiles_sidecar, "w", encoding="utf-8") as pf:
                json.dump(self.get_all_user_profiles(), pf, indent=2)

            self.log_audit(actor, "BACKUP_TIER2_AUTH_CREATED", json.dumps({"backup_path": dst_db, "tier": "auth"}))
            return {
                "success": True,
                "tier": "auth",
                "tier_label": "Tier 2 · Authentication & User Profiles",
                "backup_path": dst_db,
                "filename": os.path.basename(dst_db),
                "sha256": sha256_file(dst_db)
            }

        if tier in ("library", "library_full"):
            lib = self.get_library(library_id) if library_id else None
            if not lib:
                active = self.get_active_libraries()
                lib = active[0] if active else (self.get_libraries()[0] if self.get_libraries() else None)
            if not lib or not os.path.isdir(lib["path"]):
                raise ValueError("No valid connected Calibre library directory found to back up.")

            lib_path = os.path.abspath(lib["path"])
            meta_db = os.path.join(lib_path, "metadata.db")
            if not os.path.isfile(meta_db):
                raise ValueError(f"Calibre metadata.db not found in {lib_path}")

            safe_lid = lib["library_id"]
            zip_filename = f"calibre_library_backup_{safe_lid}_{ts}.zip"
            zip_path = os.path.join(backup_dir, zip_filename)

            # 1. Perform safe online read-only backup of metadata.db to a temporary file
            temp_meta_fd, temp_meta_path = tempfile.mkstemp(suffix=".db")
            os.close(temp_meta_fd)
            try:
                src_conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True, timeout=10.0)
                dst_conn = sqlite3.connect(temp_meta_path)
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()
                    src_conn.close()

                # Count books in snapshot
                chk_conn = sqlite3.connect(f"file:{temp_meta_path}?mode=ro", uri=True)
                books_count = chk_conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] or 0
                chk_conn.close()

                file_hashes = {}
                files_archived = 0
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    # Write consistent metadata.db snapshot
                    zf.write(temp_meta_path, arcname="metadata.db")
                    file_hashes["metadata.db"] = sha256_file(temp_meta_path)
                    files_archived += 1

                    # Walk all book folders, covers, OPFs, EPUBs, PDFs
                    for root, _, files in os.walk(lib_path):
                        for f in files:
                            full_p = os.path.join(root, f)
                            rel_p = os.path.relpath(full_p, lib_path).replace("\\", "/")
                            if rel_p == "metadata.db" or rel_p.endswith("-journal") or rel_p.endswith("-wal") or rel_p.endswith("-shm"):
                                continue
                            zf.write(full_p, arcname=rel_p)
                            file_hashes[rel_p] = sha256_file(full_p)
                            files_archived += 1

                    verification_manifest = {
                        "backup_type": "complete_calibre_library_archive",
                        "tier": "Tier 3 · Complete Calibre Library Archive",
                        "library_id": safe_lid,
                        "display_name": lib["display_name"],
                        "source_path": lib_path,
                        "created_at_utc": datetime.now(timezone.utc).isoformat(),
                        "books_count": books_count,
                        "files_count": files_archived,
                        "file_sha256": file_hashes
                    }
                    zf.writestr("backup_verification.json", json.dumps(verification_manifest, indent=2))
            finally:
                if os.path.exists(temp_meta_path):
                    os.remove(temp_meta_path)

            self.log_audit(actor, "BACKUP_TIER3_LIBRARY_ARCHIVE_CREATED", json.dumps({
                "backup_path": zip_path, "library_id": safe_lid, "books_count": books_count, "files_count": files_archived
            }))
            return {
                "success": True,
                "tier": "library",
                "tier_label": "Tier 3 · Complete Calibre Library Archive",
                "backup_path": zip_path,
                "filename": zip_filename,
                "books_count": books_count,
                "files_count": files_archived,
                "files_archived": files_archived,
                "sha256": sha256_file(zip_path)
            }

        raise ValueError(f"Unsupported backup tier: {tier}")

    def list_backups(self) -> list:
        backup_dir = Path(self.get_backups_directory())
        items = []
        for f in sorted(backup_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not f.is_file() or f.name.endswith(".profiles.json"):
                continue
            name = f.name
            if name.startswith("institutional_config_"):
                tier = "Tier 1 · Configuration & Branding"
                tier_code = "config"
            elif name.startswith("server-users_"):
                tier = "Tier 2 · Authentication & Roles"
                tier_code = "auth"
            elif name.startswith("calibre_library_backup_") and name.endswith(".zip"):
                tier = "Tier 3 · Complete Calibre Library Archive"
                tier_code = "library"
            else:
                continue

            stat = f.stat()
            dt = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            size_kb = f"{max(1, round(stat.st_size / 1024))} KB"
            items.append({
                "filename": name,
                "tier": tier,
                "tier_code": tier_code,
                "created_at": dt,
                "size_bytes": stat.st_size,
                "size_kb": size_kb,
                "path": str(f)
            })
        return items

    def verify_backup(self, filename: str) -> dict:
        backup_dir = Path(self.get_backups_directory()).resolve()
        target = (backup_dir / os.path.basename(filename)).resolve()
        if not str(target).startswith(str(backup_dir)) or not target.is_file():
            raise FileNotFoundError(f"Backup file not found: {filename}")

        file_hash = sha256_file(str(target))
        if target.name.endswith(".sqlite.bak"):
            conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=5.0)
            try:
                res = conn.execute("PRAGMA integrity_check").fetchone()
                ok = (res and res[0] == "ok")
                tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            finally:
                conn.close()
            return {
                "valid": bool(ok),
                "filename": target.name,
                "integrity": "ok" if ok else "corrupted",
                "tables": tables,
                "sha256": file_hash
            }

        if target.name.endswith(".zip"):
            with zipfile.ZipFile(str(target), "r") as zf:
                bad_file = zf.testzip()
                if bad_file is not None:
                    return {"valid": False, "filename": target.name, "error": f"Corrupted archive member: {bad_file}"}
                namelist = set(zf.namelist())
                if "metadata.db" not in namelist or "backup_verification.json" not in namelist:
                    return {"valid": False, "filename": target.name, "error": "Missing metadata.db or backup_verification.json in library archive"}
                manifest = json.loads(zf.read("backup_verification.json").decode("utf-8"))
                # Verify SHA-256 of every archived file against manifest
                for rel_p, expected_hash in manifest.get("file_sha256", {}).items():
                    if rel_p not in namelist:
                        return {"valid": False, "filename": target.name, "error": f"Missing archived book file: {rel_p}"}
                    actual_hash = hashlib.sha256(zf.read(rel_p)).hexdigest()
                    if actual_hash != expected_hash:
                        return {"valid": False, "filename": target.name, "error": f"Checksum mismatch for {rel_p}"}
            return {
                "valid": True,
                "filename": target.name,
                "integrity": "ok",
                "books_count": manifest.get("books_count", 0),
                "files_count": manifest.get("files_count", 0),
                "sha256": file_hash
            }

        raise ValueError("Unsupported backup format for verification.")

    def restore_backup(self, filename: str, userdb_path: str = None, target_library_dir: str = None, actor: str = "SYSTEM") -> dict:
        verification = self.verify_backup(filename)
        if not verification.get("valid"):
            raise ValueError(f"Backup verification failed before restore: {verification.get('error', 'Integrity check failed')}")

        backup_dir = Path(self.get_backups_directory()).resolve()
        target = (backup_dir / os.path.basename(filename)).resolve()

        if target.name.startswith("institutional_config_") and target.name.endswith(".sqlite.bak"):
            # Pre-restore safety snapshot
            self.backup_database(actor=f"{actor}:PreRestore")
            src_conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=5.0)
            with self.get_connection() as dst_conn:
                src_conn.backup(dst_conn)
            src_conn.close()
            self.ensure_schema()
            self.log_audit(actor, "BACKUP_TIER1_CONFIG_RESTORED", json.dumps({"filename": target.name}))
            return {"success": True, "tier": "config", "restored_from": target.name}

        if target.name.startswith("server-users_") and target.name.endswith(".sqlite.bak"):
            if not userdb_path:
                userdb_path = os.path.join(os.path.dirname(self.db_path), "server-users.sqlite")
            src_conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=5.0)
            dst_conn = sqlite3.connect(userdb_path, timeout=10.0)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

            profiles_sidecar = str(target) + ".profiles.json"
            if os.path.isfile(profiles_sidecar):
                with open(profiles_sidecar, "r", encoding="utf-8") as pf:
                    profiles = json.load(pf)
                for uname, pdata in profiles.items():
                    self.set_user_profile(
                        username=uname,
                        role=pdata.get("role", "Patron"),
                        display_name=pdata.get("display_name", uname),
                        department=pdata.get("department", ""),
                        is_active=pdata.get("is_active", True),
                        allowed_libraries=pdata.get("allowed_libraries", "*"),
                        actor=actor
                    )
            self.log_audit(actor, "BACKUP_TIER2_AUTH_RESTORED", json.dumps({"filename": target.name}))
            return {"success": True, "tier": "auth", "restored_from": target.name}

        if target.name.startswith("calibre_library_backup_") and target.name.endswith(".zip"):
            with zipfile.ZipFile(str(target), "r") as zf:
                manifest = json.loads(zf.read("backup_verification.json").decode("utf-8"))
                dest_dir = target_library_dir or manifest.get("source_path")
                if not dest_dir:
                    raise ValueError("No target library directory specified for Tier 3 library restore.")
                dest_dir = os.path.abspath(dest_dir)
                os.makedirs(dest_dir, exist_ok=True)
                for member in zf.namelist():
                    if member == "backup_verification.json":
                        continue
                    member_dest = os.path.abspath(os.path.join(dest_dir, member))
                    if not member_dest.startswith(dest_dir):
                        raise ValueError("Unsafe path in archive rejected.")
                    os.makedirs(os.path.dirname(member_dest), exist_ok=True)
                    with open(member_dest, "wb") as out_f:
                        out_f.write(zf.read(member))
            self.log_audit(actor, "BACKUP_TIER3_LIBRARY_RESTORED", json.dumps({
                "filename": target.name, "destination": dest_dir, "books_count": manifest.get("books_count", 0)
            }))
            return {
                "success": True,
                "tier": "library",
                "restored_from": target.name,
                "destination": dest_dir,
                "books_count": manifest.get("books_count", 0)
            }

        raise ValueError(f"Unrecognized backup file type: {filename}")

    # --------------------------------------------------------------------------
    # Immutable Audit Log API (With Filtering & Pagination)
    # --------------------------------------------------------------------------
    def log_audit(self, actor, action, details=None, conn=None):
        now = datetime.now(timezone.utc).isoformat()
        if isinstance(details, (dict, list)):
            details_str = json.dumps(details)
        else:
            details_str = str(details) if details is not None else None
        if conn is not None:
            conn.execute("""
                INSERT INTO audit_records (timestamp, actor, action, details)
                VALUES (?, ?, ?, ?)
            """, (now, str(actor), str(action), details_str))
            return True
        with self.get_connection() as c:
            c.execute("""
                INSERT INTO audit_records (timestamp, actor, action, details)
                VALUES (?, ?, ?, ?)
            """, (now, str(actor), str(action), details_str))
        return True

    def get_audit_log(self, limit=50):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_records ORDER BY id DESC LIMIT ?", (int(limit),))
            return [dict(r) for r in cur.fetchall()]

    def query_audit_log(self, limit=50, offset=0, q="", category="ALL") -> dict:
        limit = max(1, min(500, int(limit or 50)))
        offset = max(0, int(offset or 0))
        q = (q or "").strip().lower()
        category = (category or "ALL").strip().upper()

        clauses = []
        params = []
        if q:
            clauses.append("(lower(actor) LIKE ? OR lower(action) LIKE ? OR lower(coalesce(details, '')) LIKE ?)")
            like_q = f"%{q}%"
            params.extend([like_q, like_q, like_q])
        if category and category != "ALL":
            clauses.append("upper(action) LIKE ?")
            params.append(f"%{category}%")

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM audit_records {where_sql}", params)
            total = cur.fetchone()[0] or 0

            cur.execute(
                f"SELECT * FROM audit_records {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [limit, offset]
            )
            records = [dict(r) for r in cur.fetchall()]

        return {
            "items": records,
            "records": records,
            "total": total,
            "offset": offset,
            "limit": limit
        }


# Global Singleton Instance
_GLOBAL_CONFIG_MANAGER = None


def get_config_manager():
    global _GLOBAL_CONFIG_MANAGER
    if _GLOBAL_CONFIG_MANAGER is None:
        _GLOBAL_CONFIG_MANAGER = ConfigManager()
    return _GLOBAL_CONFIG_MANAGER
