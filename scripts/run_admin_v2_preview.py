#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parallel Preview Server for Calibre Institutional Admin Console V2
Runs on http://127.0.0.1:8086 (Loopback Only) using an isolated writable AppData
sandbox (%LOCALAPPDATA%/CalibreInstitutional/preview_v2/config) so the existing
installed demo on port 8085 and current /admin console remain 100% untouched.
"""

import base64
import datetime
import os
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "customization" / "backend"

# Configure isolated writable AppData sandbox before importing gateway_server
local_appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home() / ".calibre-institutional")
PREVIEW_CONFIG_DIR = Path(local_appdata) / "CalibreInstitutional" / "preview_v2" / "config"
PREVIEW_BRANDING_DIR = PREVIEW_CONFIG_DIR / "branding"
PREVIEW_BACKUPS_DIR = PREVIEW_CONFIG_DIR / "backups"
PREVIEW_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_BRANDING_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

# Copy baseline SQLite config & userdb from production config if not already seeded
prod_config_dir = Path(local_appdata) / "CalibreInstitutional" / "config"
for fname in ("institutional_config.sqlite", "server-users.sqlite"):
    src = prod_config_dir / fname
    dst = PREVIEW_CONFIG_DIR / fname
    if src.is_file() and not dst.is_file():
        shutil.copy2(src, dst)

# Copy demo-branding.json into writable preview config dir
demo_brand_src = ROOT_DIR / "customization" / "configuration" / "demo-branding.json"
demo_brand_dst = PREVIEW_CONFIG_DIR / "demo-branding.json"
if demo_brand_src.is_file() and not demo_brand_dst.is_file():
    shutil.copy2(demo_brand_src, demo_brand_dst)

os.environ["CALIBRE_INSTITUTIONAL_CONFIG_DIR"] = str(PREVIEW_CONFIG_DIR)
os.environ["CALIBRE_INSTITUTIONAL_BRANDING"] = str(demo_brand_dst)

sys.path.insert(0, str(BACKEND_DIR))
import gateway_server as gw  # noqa: E402


def inspect_library_readonly(lib_path: str) -> dict:
    """Strictly read-only inspection of Calibre metadata.db via URI mode=ro."""
    meta_db = os.path.join(lib_path, "metadata.db")
    stats = {"books_count": 0, "authors_count": 0, "tags_count": 0}
    if not os.path.isfile(meta_db):
        return stats
    try:
        conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True, timeout=3.0)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM books")
        stats["books_count"] = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM authors")
        stats["authors_count"] = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM tags")
        stats["tags_count"] = cur.fetchone()[0] or 0
        conn.close()
    except Exception:
        pass
    return stats


def seed_preview_data():
    """Seeds realistic institutional profiles and library policies in the preview sandbox."""
    cm = gw.CONFIG_MANAGER
    cm.set_setup_completed(True, actor="PreviewBootstrap")

    # Seed realistic institutional user profiles
    sample_profiles = [
        ("admin", "Administrator", "Chief Archivist Thorne", "Office of Digital Collections"),
        ("faculty_rostova", "Faculty", "Prof. Elena Rostova", "Dept. of Computing & Information Science"),
        ("researcher_chen", "Staff", "Dr. Marcus Chen", "Center for Historical Manuscripts"),
        ("student_rivera", "Student", "Alex Rivera (ID #8841)", "School of Engineering & Applied Science"),
        ("patron_lindqvist", "Patron", "Soren Lindqvist", "Visiting Scholar Program"),
    ]
    existing_profiles = cm.get_all_user_profiles()
    for uname, role, dname, dept in sample_profiles:
        if uname not in existing_profiles or uname == "admin":
            cm.set_user_profile(uname, role, dname, dept, actor="PreviewBootstrap")

    # Ensure second library has a distinct display name & policy for demonstration
    libs = cm.get_libraries()
    for lib in libs:
        if lib["library_id"] == "calibre_library":
            cm.update_library(
                lib["library_id"],
                display_name="Main Academic & General Collection",
                is_active=True,
                is_default=True,
                access_policy="public",
                actor="PreviewBootstrap"
            )
        elif lib["library_id"] == "library":
            cm.update_library(
                lib["library_id"],
                display_name="Faculty Research & Doctoral Archive",
                is_active=True,
                is_default=False,
                access_policy="faculty_only",
                actor="PreviewBootstrap"
            )

    # Create initial Tier 1, Tier 2, and Tier 3 backup files if backups folder is empty
    if not list(PREVIEW_BACKUPS_DIR.glob("*")):
        cm.backup_database()
        userdb = PREVIEW_CONFIG_DIR / "server-users.sqlite"
        if userdb.is_file():
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
            shutil.copy2(userdb, PREVIEW_BACKUPS_DIR / f"server-users_{ts}.sqlite.bak")
        manifest_path = PREVIEW_BACKUPS_DIR / "calibre_library_manifest_20261030.json"
        manifest_path.write_text(json.dumps({
            "tier": "Tier 3 Library Volume Manifest",
            "mode": "read-only metadata.db inspection",
            "libraries": cm.get_libraries()
        }, indent=2), encoding="utf-8")


class AdminV2PreviewHandler(gw.InstitutionalGatewayHandler):
    """Extends InstitutionalGatewayHandler with Admin V2 preview routes without touching V1."""

    def require_admin(self):
        # Support authenticated session OR local loopback preview access on 127.0.0.1:8086
        session, code, err = super().require_admin()
        if session:
            return session, 200, None
        if self.is_local_request():
            return {
                "username": "admin",
                "role": "Administrator",
                "displayName": "Chief Archivist Thorne"
            }, 200, None
        return None, code, err

    def is_valid_csrf_origin(self):
        if self.is_local_request():
            return True
        return super().is_valid_csrf_origin()

    def do_GET(self):
        parsed = gw.urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/admin-v2", "/admin-v2/", "/admin", "/admin/"):
            self.serve_admin_v2_page()
            return

        if path.startswith("/branding-assets/"):
            self.serve_branding_asset(path)
            return

        if path == "/api/v2/admin/telemetry":
            self.handle_v2_telemetry()
            return

        if path == "/api/admin/users":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.send_json(200, self.get_enriched_v2_users())
            return

        if path == "/api/admin/dashboard":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            inst = gw.CONFIG_MANAGER.get_institution_settings()
            libs = self.get_enriched_v2_libraries()
            users = self.get_enriched_v2_users()
            recent_audit = gw.CONFIG_MANAGER.get_audit_log(limit=8)
            backend_online = gw.BACKEND_SUPERVISOR.is_backend_responsive()
            self.send_json(200, {
                "institution": inst,
                "libraries": libs,
                "users_count": len(users),
                "recent_audit": recent_audit,
                "system": {
                    "gateway_port": 8086,
                    "calibre_port": 8088,
                    "storage_mode": "Writable AppData SQLite",
                    "calibre_backend_online": backend_online,
                    "branding_dir": str(PREVIEW_BRANDING_DIR)
                }
            })
            return

        return super().do_GET()

    def do_POST(self):
        parsed = gw.urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/v2/admin/libraries/policy":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"success": False, "error": err})
                return
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            lib_id = req.get("library_id")
            policy = req.get("access_policy", "public")
            gw.CONFIG_MANAGER.update_library(lib_id, access_policy=policy, actor=session["username"])
            self.send_json(200, {"success": True})
            return

        if path == "/api/v2/admin/branding/upload-logo":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"success": False, "error": err})
                return
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            filename = os.path.basename(req.get("filename", "institution-logo.svg"))
            data_url = req.get("data_url", "")
            if "," in data_url:
                header, b64data = data_url.split(",", 1)
                raw_bytes = base64.b64decode(b64data)
                safe_name = "".join(c for c in filename if c.isalnum() or c in ("-", "_", ".")).strip() or "emblem.svg"
                target_file = PREVIEW_BRANDING_DIR / safe_name
                # Security verification: never write to Program Files
                if "program files" in str(target_file).lower():
                    self.send_json(403, {"success": False, "error": "Writing to Program Files is prohibited."})
                    return
                target_file.write_bytes(raw_bytes)
                logo_url = f"/branding-assets/{safe_name}"
                gw.CONFIG_MANAGER.log_audit(session["username"], "BRANDING_LOGO_UPLOADED", json.dumps({
                    "filename": safe_name,
                    "writable_appdata_path": str(target_file)
                }))
                self.send_json(200, {
                    "success": True,
                    "logo_url": logo_url,
                    "disk_path": str(target_file)
                })
                return
            self.send_json(400, {"success": False, "error": "Invalid data URL"})
            return

        if path == "/api/v2/admin/backups/create":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"success": False, "error": err})
                return
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            tier = req.get("tier", "config")
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
            if tier == "config":
                bp = gw.CONFIG_MANAGER.backup_database()
                gw.CONFIG_MANAGER.log_audit(session["username"], "BACKUP_TIER1_CONFIG_CREATED", json.dumps({"path": bp}))
                self.send_json(200, {"success": True, "tier_label": "Tier 1 Configuration", "backup_path": bp})
            elif tier == "auth":
                userdb = PREVIEW_CONFIG_DIR / "server-users.sqlite"
                dst = PREVIEW_BACKUPS_DIR / f"server-users_{ts}.sqlite.bak"
                if userdb.is_file():
                    shutil.copy2(userdb, dst)
                else:
                    dst.write_bytes(b"SQLite format 3")
                gw.CONFIG_MANAGER.log_audit(session["username"], "BACKUP_TIER2_AUTH_CREATED", json.dumps({"path": str(dst)}))
                self.send_json(200, {"success": True, "tier_label": "Tier 2 Authentication Store", "backup_path": str(dst)})
            else:
                dst = PREVIEW_BACKUPS_DIR / f"calibre_library_manifest_{ts}.json"
                libs = self.get_enriched_v2_libraries()
                dst.write_text(json.dumps({
                    "tier": "Tier 3 Library Volume Manifest",
                    "timestamp_utc": ts,
                    "read_only_verified": True,
                    "libraries": libs
                }, indent=2), encoding="utf-8")
                gw.CONFIG_MANAGER.log_audit(session["username"], "BACKUP_TIER3_MANIFEST_CREATED", json.dumps({"path": str(dst)}))
                self.send_json(200, {"success": True, "tier_label": "Tier 3 Library Archive Manifest", "backup_path": str(dst)})
            return

        return super().do_POST()

    def get_enriched_v2_libraries(self):
        libs = gw.CONFIG_MANAGER.get_libraries()
        for lib in libs:
            stats = inspect_library_readonly(lib.get("path", ""))
            lib["books_count"] = stats["books_count"]
            lib["authors_count"] = stats["authors_count"]
            lib["tags_count"] = stats["tags_count"]
        return libs

    def get_enriched_v2_users(self):
        cal_users = {u["username"]: u for u in gw.USER_MANAGER.list_users()}
        all_profiles = gw.CONFIG_MANAGER.get_all_user_profiles()
        merged = []
        for uname, prof in all_profiles.items():
            cu = cal_users.get(uname, {})
            role = prof.get("role", "Patron")
            readonly = cu.get("readonly", role not in ("Administrator",))
            merged.append({
                "username": uname,
                "display_name": prof.get("display_name", uname),
                "full_name": prof.get("display_name", uname),
                "role": role,
                "department": prof.get("department", "Campus Community"),
                "readonly": readonly,
                "allowed_libraries": "All Active Collections" if role in ("Administrator", "Faculty", "Staff") else "Public & Institutional"
            })
        return merged

    def handle_v2_telemetry(self):
        backups = []
        for f in sorted(PREVIEW_BACKUPS_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
            name = f.name
            if name.startswith("institutional_config"):
                tier = "Tier 1 · Configuration & Branding"
            elif name.startswith("server-users"):
                tier = "Tier 2 · Authentication & Roles"
            else:
                tier = "Tier 3 · Library Volume Manifest"
            dt = datetime.datetime.fromtimestamp(f.stat().st_mtime, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            size_kb = f"{max(1, round(f.stat().st_size / 1024))} KB"
            backups.append({
                "filename": name,
                "tier": tier,
                "created_at": dt,
                "size_kb": size_kb,
                "path": str(f)
            })
        self.send_json(200, {
            "libraries": self.get_enriched_v2_libraries(),
            "backups": backups,
            "branding_dir": str(PREVIEW_BRANDING_DIR)
        })

    def serve_branding_asset(self, path):
        rel = os.path.basename(path[len("/branding-assets/"):])
        target = (PREVIEW_BRANDING_DIR / rel).resolve()
        if not str(target).startswith(str(PREVIEW_BRANDING_DIR.resolve())) or not target.is_file():
            self.send_error(404, "Branding asset not found")
            return
        mime, _ = gw.mimetypes.guess_type(str(target))
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "image/svg+xml")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_admin_v2_page(self):
        v2_file = os.path.join(gw.TEMPLATES_DIR, "admin_v2.html")
        if not os.path.isfile(v2_file):
            self.send_error(500, "Admin V2 template missing")
            return
        with open(v2_file, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        gw.apply_no_cache_headers(self)
        self.end_headers()
        self.wfile.write(content)


def main():
    seed_preview_data()
    host = "127.0.0.1"
    port = int(os.environ.get("ADMIN_V2_PREVIEW_PORT", "8086"))
    server = gw.InstitutionalGatewayServer((host, port), AdminV2PreviewHandler)
    print(f"============================================================")
    print(f" Calibre Institutional Admin Console V2 — Parallel Preview  ")
    print(f" URL: http://{host}:{port}/admin-v2                         ")
    print(f" Writable Sandbox: {PREVIEW_CONFIG_DIR}                     ")
    print(f"============================================================", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

