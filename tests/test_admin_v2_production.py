"""
Comprehensive Production Acceptance & Regression Test Suite for
Calibre Institutional Admin Console V2 (All 8 Modules).

Runs in an isolated temporary configuration directory so existing production/demo
data is never mutated during automated testing.
"""

import base64
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = tempfile.TemporaryDirectory(prefix="calibre-admin-v2-prod-test-")
os.environ["CALIBRE_INSTITUTIONAL_CONFIG_DIR"] = TEST_DIR.name
os.environ["CALIBRE_INSTITUTIONAL_GATEWAY_CONFIG"] = str(
    ROOT / "customization" / "configuration" / "gateway_config.json"
)

sys.path.insert(0, str(ROOT / "customization" / "backend"))
sys.path.insert(0, str(ROOT / "upstream" / "calibre" / "src"))

import gateway_server as gateway
from config_manager import ConfigManager


def create_sample_calibre_library(lib_dir: Path, books=None):
    """Creates a realistic Calibre metadata.db and book files for read-only inspection & backup tests."""
    lib_dir.mkdir(parents=True, exist_ok=True)
    db_path = lib_dir / "metadata.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            sort TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            pubdate TEXT DEFAULT CURRENT_TIMESTAMP,
            series_index REAL DEFAULT 1.0,
            author_sort TEXT,
            isbn TEXT DEFAULT '',
            lccn TEXT DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            flags INTEGER DEFAULT 1,
            uuid TEXT DEFAULT 'uuid-1',
            has_cover BOOL DEFAULT 1,
            last_modified TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sort TEXT
        );
        CREATE TABLE books_authors_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book INTEGER NOT NULL,
            author INTEGER NOT NULL
        );
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE books_tags_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book INTEGER NOT NULL,
            tag INTEGER NOT NULL
        );
        CREATE TABLE series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sort TEXT
        );
        CREATE TABLE books_series_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book INTEGER NOT NULL,
            series INTEGER NOT NULL
        );
        CREATE TABLE publishers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sort TEXT
        );
        CREATE TABLE books_publishers_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book INTEGER NOT NULL,
            publisher INTEGER NOT NULL
        );
        CREATE TABLE data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book INTEGER NOT NULL,
            format TEXT NOT NULL,
            uncompressed_size INTEGER DEFAULT 1024,
            name TEXT NOT NULL
        );
        """
    )

    sample_books = books or [
        ("Distributed Systems Architecture", "Prof. Elena Rostova", "Computer Science", "Academic Press", "Foundations", "EPUB"),
        ("Quantum Cryptography & Protocols", "Dr. Marcus Vance", "Cryptography", "MIT Press", "Security", "PDF"),
        ("Classical Archival Preservation", "Sarah Jenkins", "Library Science", "Oxford Press", "Archives", "EPUB"),
    ]

    for idx, (title, author, tag, publisher, series_name, fmt) in enumerate(sample_books, start=1):
        rel_path = f"{author}/{title} ({idx})"
        book_folder = lib_dir / author / f"{title} ({idx})"
        book_folder.mkdir(parents=True, exist_ok=True)
        book_file = book_folder / f"{title}.{fmt.lower()}"
        book_file.write_bytes(f"Sample {fmt} content for {title}".encode("utf-8"))
        (book_folder / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0JFIF-sample-cover")

        cur.execute(
            "INSERT INTO books (id, title, sort, author_sort, path, has_cover) VALUES (?, ?, ?, ?, ?, 1)",
            (idx, title, title, author, rel_path),
        )
        cur.execute("INSERT INTO authors (id, name, sort) VALUES (?, ?, ?)", (idx, author, author))
        cur.execute("INSERT INTO books_authors_link (book, author) VALUES (?, ?)", (idx, idx))
        cur.execute("INSERT INTO tags (id, name) VALUES (?, ?)", (idx, tag))
        cur.execute("INSERT INTO books_tags_link (book, tag) VALUES (?, ?)", (idx, idx))
        cur.execute("INSERT INTO publishers (id, name, sort) VALUES (?, ?, ?)", (idx, publisher, publisher))
        cur.execute("INSERT INTO books_publishers_link (book, publisher) VALUES (?, ?)", (idx, idx))
        cur.execute("INSERT INTO series (id, name, sort) VALUES (?, ?, ?)", (idx, series_name, series_name))
        cur.execute("INSERT INTO books_series_link (book, series) VALUES (?, ?)", (idx, idx))
        cur.execute(
            "INSERT INTO data (book, format, uncompressed_size, name) VALUES (?, ?, ?, ?)",
            (idx, fmt, book_file.stat().st_size, title),
        )

    conn.commit()
    conn.close()
    return db_path


class AdminV2ProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_path = Path(TEST_DIR.name)
        cls.primary_lib = cls.base_path / "PrimaryLibrary"
        cls.faculty_lib = cls.base_path / "FacultyResearchLibrary"
        create_sample_calibre_library(cls.primary_lib)
        create_sample_calibre_library(
            cls.faculty_lib,
            books=[
                ("Restricted Faculty Monograph", "Dr. Helena Thorne", "Research", "Aethelgard Press", "Fellows", "PDF"),
            ],
        )

        # Create a sample server-users.sqlite for Tier 2 Auth backup tests
        cls.userdb_path = cls.base_path / "server-users.sqlite"
        uconn = sqlite3.connect(str(cls.userdb_path))
        uconn.execute("CREATE TABLE users (name TEXT PRIMARY KEY, pw TEXT, timestamp TEXT, session_data TEXT, restriction TEXT, readonly TEXT)")
        uconn.execute("INSERT INTO users VALUES ('admin', 'hash', 'now', '{}', '{}', 'n')")
        uconn.commit()
        uconn.close()

        # Re-initialize gateway CONFIG_MANAGER against isolated test directory
        gateway.CONFIG_MANAGER = ConfigManager(
            db_path=str(cls.base_path / "institutional_config.sqlite"),
        )
        gateway.USER_MANAGER.config_manager = gateway.CONFIG_MANAGER
        gateway.USER_MANAGER.userdb_path = str(cls.userdb_path)

        # Register primary library and mark setup completed
        gateway.CONFIG_MANAGER.add_library(
            display_name="Main Academic Collection",
            path=str(cls.primary_lib),
            is_default=True,
            is_active=True,
            access_policy="public",
            actor="TestSetup",
        )
        gateway.CONFIG_MANAGER.set_user_profile(
            username="admin",
            display_name="Chief Archivist",
            role="Administrator",
            department="Library Governance",
            is_active=True,
            allowed_libraries="*",
            actor="TestSetup",
        )
        gateway.CONFIG_MANAGER.set_setup_completed(True, actor="TestSetup")

    def make_handler(self, path="/", method="GET", body_dict=None, session=None, headers=None):
        h = object.__new__(gateway.InstitutionalGatewayHandler)
        h.client_address = ("127.0.0.1", 54321)
        h.path = path
        h.command = method
        raw_body = json.dumps(body_dict).encode("utf-8") if body_dict is not None else b""
        req_headers = {
            "Host": "127.0.0.1:8085",
            "Origin": "http://127.0.0.1:8085",
            "Content-Length": str(len(raw_body)),
        }
        if session:
            token = f"tok-{session['username']}"
            gateway.SESSIONS[token] = dict(session, expires_at=9999999999.0, last_active=9999999999.0)
            req_headers["Cookie"] = f"{gateway.COOKIE_NAME}={token}"
        if headers:
            req_headers.update(headers)
        h.headers = req_headers
        h.rfile = io.BytesIO(raw_body)
        h.wfile = io.BytesIO()
        h.status_code = None
        h.response_headers = {}
        h.json_response = None

        def send_response(code, message=None):
            h.status_code = code

        def send_header(k, v):
            h.response_headers[k] = v

        def end_headers():
            pass

        def send_json(code, data, extra_headers=None):
            h.status_code = code
            h.json_response = data

        h.send_response = send_response
        h.send_header = send_header
        h.end_headers = end_headers
        h.send_json = send_json
        return h

    # =========================================================================
    # MODULE 1: DASHBOARD OVERVIEW
    # =========================================================================
    def test_01_dashboard_real_telemetry_and_admin_html(self):
        admin_sess = {"username": "admin", "role": "Administrator", "readonly": False}

        # 1. Verify /admin serves Admin Console V2 HTML to Administrator
        h_html = self.make_handler("/admin", session=admin_sess)
        h_html.serve_admin_page()
        self.assertEqual(h_html.status_code, 200)
        html_text = h_html.wfile.getvalue().decode("utf-8")
        self.assertIn("Institutional Administration Console V2", html_text)
        self.assertIn("Dashboard Overview", html_text)
        self.assertIn("Local DNS &amp; Campus Network Deployment Requirements", html_text)
        self.assertIn("Complete Calibre Library (.zip)", html_text)

        # 2. Verify non-admin is blocked with 403
        student_sess = {"username": "student1", "role": "Student", "readonly": True}
        h_forbid = self.make_handler("/admin", session=student_sess)
        h_forbid.serve_admin_page()
        self.assertEqual(h_forbid.status_code, 403)

        # 3. Verify /api/admin/dashboard returns accurate book counts, libraries, and catalogue settings
        h_dash = self.make_handler("/api/admin/dashboard", session=admin_sess)
        with patch.object(gateway.USER_MANAGER, "list_users", return_value=[{"username": "admin", "role": "Administrator", "is_active": True}]):
            h_dash.do_GET()
        self.assertEqual(h_dash.status_code, 200)
        dash = h_dash.json_response
        self.assertEqual(dash["system"]["total_books"], 3)
        self.assertEqual(len(dash["libraries"]), 1)
        self.assertEqual(dash["libraries"][0]["books_count"], 3)
        self.assertEqual(dash["libraries"][0]["authors_count"], 3)
        self.assertIn("catalogue_settings", dash)

    # =========================================================================
    # MODULE 2: USERS & ACCESS MANAGEMENT (DEACTIVATION & PER-LIBRARY SCOPE)
    # =========================================================================
    def test_02_users_lifecycle_deactivation_and_per_library_enforcement(self):
        admin_sess = {"username": "admin", "role": "Administrator", "readonly": False}

        # Connect second restricted library (faculty_only)
        h_add_lib = self.make_handler(
            "/api/admin/libraries",
            method="POST",
            body_dict={
                "display_name": "Faculty Research Archive",
                "library_path": str(self.faculty_lib),
                "access_policy": "faculty_only",
                "is_default": False,
            },
            session=admin_sess,
        )
        h_add_lib.handle_admin_posts("/api/admin/libraries", admin_sess)
        self.assertEqual(h_add_lib.status_code, 200)
        faculty_lib_id = h_add_lib.json_response["library_id"]

        # Create a Student account with default '*' library scope
        with patch.object(gateway.USER_MANAGER, "_run_manage_users", return_value=types.SimpleNamespace(returncode=0, stdout="Added", stderr="")):
            h_create = self.make_handler(
                "/api/admin/users/create",
                method="POST",
                body_dict={
                    "username": "student_alex",
                    "password": "Password123!",
                    "full_name": "Alex Rivera",
                    "role": "Student",
                    "department": "Physics",
                    "readonly": True,
                    "allowed_libraries": "*",
                },
                session=admin_sess,
            )
            h_create.handle_admin_posts("/api/admin/users/create", admin_sess)
            self.assertEqual(h_create.status_code, 200)

        # Verify backend per-library authorization:
        # Student with '*' can access public library, but is blocked from 'faculty_only' library!
        self.assertTrue(gateway.CONFIG_MANAGER.is_user_allowed_library("student_alex", "Student", "primarylibrary"))
        self.assertFalse(gateway.CONFIG_MANAGER.is_user_allowed_library("student_alex", "Student", faculty_lib_id))
        self.assertTrue(gateway.CONFIG_MANAGER.is_user_allowed_library("prof_rostova", "Faculty", faculty_lib_id))

        # Verify proxy blocks Student from accessing restricted library via /calibre/institutional/api
        student_sess = {"username": "student_alex", "role": "Student", "readonly": True}
        h_proxy_denied = self.make_handler(
            f"/calibre/institutional/api?library_id={faculty_lib_id}",
            session=student_sess,
        )
        h_proxy_denied.proxy_to_calibre()
        self.assertEqual(h_proxy_denied.status_code, 403)
        self.assertIn("does not permit access", h_proxy_denied.json_response["error"].lower())

        # Now grant explicit per-library access to student_alex via /api/admin/users/profile
        h_grant = self.make_handler(
            "/api/admin/users/profile",
            method="POST",
            body_dict={
                "username": "student_alex",
                "full_name": "Alex Rivera (Research Assistant)",
                "role": "Student",
                "department": "Physics",
                "allowed_libraries": f"primarylibrary,{faculty_lib_id}",
            },
            session=admin_sess,
        )
        h_grant.handle_admin_posts("/api/admin/users/profile", admin_sess)
        self.assertEqual(h_grant.status_code, 200)
        self.assertTrue(gateway.CONFIG_MANAGER.is_user_allowed_library("student_alex", "Student", faculty_lib_id))

        # Test Account Deactivation -> revokes sessions and blocks login
        gateway.SESSIONS["tok-student_alex"] = {"username": "student_alex", "role": "Student", "last_active": 9999999999.0}
        h_deact = self.make_handler(
            "/api/admin/users/status",
            method="POST",
            body_dict={"username": "student_alex", "is_active": False},
            session=admin_sess,
        )
        h_deact.handle_admin_posts("/api/admin/users/status", admin_sess)
        self.assertEqual(h_deact.status_code, 200)
        self.assertNotIn("tok-student_alex", gateway.SESSIONS)
        self.assertFalse(gateway.CONFIG_MANAGER.get_user_profile("student_alex")["is_active"])

        # Verify deactivated user cannot log in (returns 403)
        h_login = self.make_handler(
            "/api/auth/login",
            method="POST",
            body_dict={"username": "student_alex", "password": "Password123!"},
        )
        h_login.do_POST()
        self.assertEqual(h_login.status_code, 403)
        self.assertIn("deactivated", h_login.json_response["error"].lower())

        # Verify primary 'admin' account cannot be deactivated
        h_deact_admin = self.make_handler(
            "/api/admin/users/status",
            method="POST",
            body_dict={"username": "admin", "is_active": False},
            session=admin_sess,
        )
        h_deact_admin.handle_admin_posts("/api/admin/users/status", admin_sess)
        self.assertEqual(h_deact_admin.status_code, 400)

    # =========================================================================
    # MODULE 3: LIBRARY MANAGEMENT (READ-ONLY VALIDATION & SAFE DISCONNECT)
    # =========================================================================
    def test_03_library_validation_policy_and_nondestructive_removal(self):
        admin_sess = {"username": "admin", "role": "Administrator", "readonly": False}

        # Validate library path in read-only mode
        h_val = self.make_handler(
            "/api/setup/validate-library",
            method="POST",
            body_dict={"library_path": str(self.primary_lib)},
            session=admin_sess,
        )
        h_val.handle_validate_library()
        self.assertEqual(h_val.status_code, 200)
        self.assertTrue(h_val.json_response["valid"])
        self.assertEqual(h_val.json_response["books_count"], 3)

        # Create a temporary secondary library and disconnect it; verify files on disk remain intact
        temp_lib = self.base_path / "TempDisconnectLib"
        create_sample_calibre_library(temp_lib)
        h_add = self.make_handler(
            "/api/admin/libraries",
            method="POST",
            body_dict={"display_name": "Temporary Collection", "library_path": str(temp_lib)},
            session=admin_sess,
        )
        h_add.handle_admin_posts("/api/admin/libraries", admin_sess)
        temp_lib_id = h_add.json_response["library_id"]

        h_rem = self.make_handler(
            "/api/admin/libraries/remove",
            method="POST",
            body_dict={"library_id": temp_lib_id},
            session=admin_sess,
        )
        h_rem.handle_admin_posts("/api/admin/libraries/remove", admin_sess)
        self.assertEqual(h_rem.status_code, 200)
        self.assertTrue((temp_lib / "metadata.db").is_file(), "Disconnecting a library must never delete metadata.db on disk")

    # =========================================================================
    # MODULE 4: CATALOGUE & METADATA SETTINGS + DOWNLOAD POLICY ENFORCEMENT
    # =========================================================================
    def test_04_catalogue_settings_and_download_policy(self):
        admin_sess = {"username": "admin", "role": "Administrator", "readonly": False}

        h_save_cat = self.make_handler(
            "/api/admin/catalogue-settings",
            method="POST",
            body_dict={
                "page_size": 48,
                "default_sort": "title_asc",
                "exposed_facets": ["authors", "tags", "formats"],
                "inject_bar": True,
                "inbrowser_reader": True,
                "download_policy": "faculty_admin",
            },
            session=admin_sess,
        )
        h_save_cat.handle_admin_posts("/api/admin/catalogue-settings", admin_sess)
        self.assertEqual(h_save_cat.status_code, 200)

        saved = gateway.CONFIG_MANAGER.get_catalogue_settings()
        self.assertEqual(saved["page_size"], 48)
        self.assertEqual(saved["default_sort"], "title_asc")
        self.assertEqual(saved["exposed_facets"], ["authors", "tags", "formats"])
        self.assertEqual(saved["download_policy"], "faculty_admin")

        # Verify download_policy="faculty_admin" blocks Student from direct file download (/calibre/get/EPUB/1)
        student_sess = {"username": "student1", "role": "Student", "readonly": True}
        h_dl = self.make_handler("/calibre/get/EPUB/1/PrimaryLibrary", session=student_sess)
        h_dl.proxy_to_calibre()
        self.assertEqual(h_dl.status_code, 403)
        self.assertIn("Direct file downloads are restricted", h_dl.json_response["error"])

        # Reset download_policy to authenticated
        gateway.CONFIG_MANAGER.update_catalogue_settings(download_policy="authenticated")

    # =========================================================================
    # MODULE 5: INSTITUTION BRANDING & WRITABLE APPDATA LOGO UPLOAD
    # =========================================================================
    def test_05_branding_and_writable_appdata_logo_upload(self):
        admin_sess = {"username": "admin", "role": "Administrator", "readonly": False}

        svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#14284b"/></svg>'
        data_url = "data:image/svg+xml;base64," + base64.b64encode(svg_bytes).decode("ascii")

        h_up = self.make_handler(
            "/api/v2/admin/branding/upload-logo",
            method="POST",
            body_dict={"filename": "st_judes_seal.svg", "data_url": data_url},
            session=admin_sess,
        )
        h_up.handle_admin_posts("/api/v2/admin/branding/upload-logo", admin_sess)
        self.assertEqual(h_up.status_code, 200)
        logo_url = h_up.json_response["logo_url"]
        disk_path = h_up.json_response["disk_path"]
        self.assertTrue(logo_url.startswith("/branding-assets/"))
        self.assertTrue(os.path.isfile(disk_path))
        self.assertNotIn("Program Files", disk_path)

        # Verify GET /branding-assets/<filename> serves the uploaded SVG
        h_asset = self.make_handler(logo_url)
        h_asset.serve_branding_asset(logo_url)
        self.assertEqual(h_asset.status_code, 200)
        self.assertIn(b"<svg", h_asset.wfile.getvalue())

        # Save institution branding settings and verify propagation
        h_brand = self.make_handler(
            "/api/admin/settings",
            method="POST",
            body_dict={
                "name": "St. Jude's College Digital Archive",
                "short_name": "SJC",
                "library_name": "Bodleian & Fellows Collection",
                "motto": "Dominus Illuminatio Mea",
                "contact_email": "archivist@stjudes.ac.uk",
                "contact_phone": "+44 1865 270000",
                "logo_url": logo_url,
                "primary_color": "#14284b",
            },
            session=admin_sess,
        )
        h_brand.handle_admin_posts("/api/admin/settings", admin_sess)
        self.assertEqual(h_brand.status_code, 200)

        inst = gateway.CONFIG_MANAGER.get_institution_settings()
        self.assertEqual(inst["name"], "St. Jude's College Digital Archive")
        self.assertEqual(inst["short_name"], "SJC")
        self.assertEqual(inst["primary_color"], "#14284b")
        self.assertEqual(inst["logo_url"], logo_url)

    # =========================================================================
    # MODULE 6: SERVER & NETWORK
    # =========================================================================
    def test_06_server_and_network_configuration(self):
        admin_sess = {"username": "admin", "role": "Administrator", "readonly": False}
        h_net = self.make_handler(
            "/api/v2/admin/network",
            method="POST",
            body_dict={
                "bind_mode": "127.0.0.1",
                "gateway_port": 8085,
                "session_timeout_seconds": 14400,
                "tls_mode": "local",
            },
            session=admin_sess,
        )
        h_net.handle_admin_posts("/api/v2/admin/network", admin_sess)
        self.assertEqual(h_net.status_code, 200)
        self.assertEqual(gateway.CONFIG_MANAGER.get_config_value("session_timeout_seconds"), "14400")
        self.assertEqual(gateway.CONFIG_MANAGER.get_config_value("network_bind_mode"), "127.0.0.1")

    # =========================================================================
    # MODULE 7: BACKUP & RECOVERY (3 SEPARATED TIERS + VERIFY + RESTORE)
    # =========================================================================
    def test_07_three_tier_backups_verification_and_restore(self):
        admin_sess = {"username": "admin", "role": "Administrator", "readonly": False}

        # Tier 1: Configuration & Branding backup
        h_b1 = self.make_handler(
            "/api/v2/admin/backups/create",
            method="POST",
            body_dict={"tier": "config"},
            session=admin_sess,
        )
        h_b1.handle_admin_posts("/api/v2/admin/backups/create", admin_sess)
        self.assertEqual(h_b1.status_code, 200)
        b1_file = h_b1.json_response["filename"]

        # Tier 2: Authentication DB backup
        h_b2 = self.make_handler(
            "/api/v2/admin/backups/create",
            method="POST",
            body_dict={"tier": "auth"},
            session=admin_sess,
        )
        h_b2.handle_admin_posts("/api/v2/admin/backups/create", admin_sess)
        self.assertEqual(h_b2.status_code, 200)
        b2_file = h_b2.json_response["filename"]

        # Tier 3: Complete Calibre Library (.zip) archive (NOT merely a manifest!)
        h_b3 = self.make_handler(
            "/api/v2/admin/backups/create",
            method="POST",
            body_dict={"tier": "library"},
            session=admin_sess,
        )
        h_b3.handle_admin_posts("/api/v2/admin/backups/create", admin_sess)
        self.assertEqual(h_b3.status_code, 200)
        b3_res = h_b3.json_response
        b3_file = b3_res["filename"]
        self.assertTrue(b3_file.endswith(".zip"))
        self.assertEqual(b3_res["books_count"], 3)
        self.assertGreaterEqual(b3_res["files_archived"], 7)  # metadata.db + 3 books + 3 covers

        # Verify Tier 3 archive contains actual book files + metadata.db + backup_verification.json
        with zipfile.ZipFile(b3_res["backup_path"], "r") as zf:
            names = zf.namelist()
            self.assertIn("metadata.db", names)
            self.assertIn("backup_verification.json", names)
            self.assertTrue(any(n.endswith(".epub") for n in names))
            self.assertTrue(any(n.endswith(".pdf") for n in names))

        # Verify Integrity endpoint on all 3 tiers
        for fname in (b1_file, b2_file, b3_file):
            h_ver = self.make_handler(
                "/api/v2/admin/backups/verify",
                method="POST",
                body_dict={"filename": fname},
                session=admin_sess,
            )
            h_ver.handle_admin_posts("/api/v2/admin/backups/verify", admin_sess)
            self.assertEqual(h_ver.status_code, 200)
            self.assertTrue(h_ver.json_response["verified"])

        # Test Restore of Tier 1 Config Snapshot after mutating institution name
        gateway.CONFIG_MANAGER.update_institution_settings(name="Temporary Mutated Name")
        self.assertEqual(gateway.CONFIG_MANAGER.get_institution_settings()["name"], "Temporary Mutated Name")

        h_rest = self.make_handler(
            "/api/v2/admin/backups/restore",
            method="POST",
            body_dict={"filename": b1_file},
            session=admin_sess,
        )
        h_rest.handle_admin_posts("/api/v2/admin/backups/restore", admin_sess)
        self.assertEqual(h_rest.status_code, 200)
        self.assertEqual(
            gateway.CONFIG_MANAGER.get_institution_settings()["name"],
            "St. Jude's College Digital Archive",
        )

    # =========================================================================
    # MODULE 8: AUDIT & SECURITY + PERSISTENCE ACROSS RESTART
    # =========================================================================
    def test_08_audit_pagination_filtering_and_restart_persistence(self):
        admin_sess = {"username": "admin", "role": "Administrator", "readonly": False}

        # 1. Legacy list contract (used by v1 tests)
        h_legacy = self.make_handler("/api/admin/audit-log", session=admin_sess)
        h_legacy.do_GET()
        self.assertEqual(h_legacy.status_code, 200)
        self.assertIsInstance(h_legacy.json_response, list)
        self.assertGreater(len(h_legacy.json_response), 5)

        # 2. V2 paginated & filtered contract
        h_page = self.make_handler(
            "/api/admin/audit-log?paginated=1&limit=3&offset=0&category=BACKUP",
            session=admin_sess,
        )
        h_page.do_GET()
        self.assertEqual(h_page.status_code, 200)
        page_data = h_page.json_response
        self.assertIn("items", page_data)
        self.assertIn("total", page_data)
        self.assertLessEqual(len(page_data["items"]), 3)
        self.assertTrue(all("BACKUP" in item["action"] for item in page_data["items"]))

        # 3. Verify persistence across fresh ConfigManager instantiation (application restart)
        restarted_cm = ConfigManager(
            db_path=str(self.base_path / "institutional_config.sqlite"),
        )
        self.assertEqual(restarted_cm.get_institution_settings()["short_name"], "SJC")
        self.assertEqual(restarted_cm.get_catalogue_settings()["page_size"], 48)
        self.assertGreaterEqual(len(restarted_cm.get_libraries()), 2)

    # =========================================================================
    # MODULE 4B: NATIVE CALIBRE INSTITUTIONAL CATALOGUE SEARCH, SORT & FACETS
    # =========================================================================
    def test_09_native_calibre_institutional_catalogue_search_sort_and_pagination(self):
        import importlib.util
        if "calibre.institutional" not in sys.modules:
            mod = types.ModuleType("calibre.institutional")
            mod.branding = lambda: {"institution_name": "St. Jude's College Digital Archive", "short_name": "SJC"}
            sys.modules["calibre.institutional"] = mod
        spec = importlib.util.spec_from_file_location(
            "calibre.srv.institutional",
            str(ROOT / "upstream" / "calibre" / "src" / "calibre" / "srv" / "institutional.py"),
        )
        inst_srv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst_srv)

        fake_books = {
            1: {"title": "Zeta Quantum Mechanics", "authors": ["Prof. Elena Rostova"], "tags": ["Physics"], "timestamp": "2026-01-01", "pubdate": "2025-05-01", "formats": ["epub"], "cover": "/cover/1"},
            2: {"title": "Alpha Distributed Systems", "authors": ["Dr. Marcus Vance"], "tags": ["Computer Science"], "timestamp": "2026-03-01", "pubdate": "2026-02-01", "formats": ["pdf"], "cover": "/cover/2"},
            3: {"title": "Beta Archival Science", "authors": ["Sarah Jenkins"], "tags": ["Library Science"], "timestamp": "2026-02-01", "pubdate": "2024-11-01", "formats": ["epub"], "cover": "/cover/3"},
        }

        class FakeDB:
            server_library_id = "PrimaryLibrary"
            safe_read_lock = tempfile.TemporaryDirectory()  # context manager

            def field_for(self, field, bid, default=None):
                b = fake_books.get(bid, {})
                if field == "authors":
                    return tuple(b.get("authors", ()))
                return b.get(field, default)

        class FakeCtx:
            def library_info(self, rd):
                return {"PrimaryLibrary": "Main Academic Collection"}, "PrimaryLibrary"

            def search(self, rd, db, query):
                rd.last_query = query
                if 'authors:"Elena"' in query:
                    return {1}
                if 'tags:"=Computer Science"' in query:
                    return {2}
                return {1, 2, 3}

            def url_for(self, *args, **kwargs):
                return "/calibre/content"

            def get_categories(self, rd, db):
                return {
                    "tags": [types.SimpleNamespace(original_name="Physics", count=1), types.SimpleNamespace(original_name="Computer Science", count=1)],
                    "authors": [types.SimpleNamespace(original_name="Prof. Elena Rostova", count=1)],
                }

        ctx = FakeCtx()
        db = FakeDB()

        with patch.object(inst_srv, "get_db", return_value=db), patch.object(
            inst_srv, "book_to_json", side_effect=lambda c, r, d, bid, **kw: (fake_books[bid], None)
        ):
            # 1. Default title_asc sort + pagination
            rd1 = types.SimpleNamespace(query={"sort": "title_asc", "limit": "2", "offset": "0"}, username="student1", outheaders={})
            res1 = inst_srv.institutional_catalog(ctx, rd1)
            self.assertEqual(res1["total"], 3)
            self.assertEqual(len(res1["books"]), 2)
            self.assertEqual([b["title"] for b in res1["books"]], ["Alpha Distributed Systems", "Beta Archival Science"])

            # 2. timestamp_desc sort
            rd2 = types.SimpleNamespace(query={"sort": "timestamp_desc", "limit": "3", "offset": "0"}, username="student1", outheaders={})
            res2 = inst_srv.institutional_catalog(ctx, rd2)
            self.assertEqual([b["id"] for b in res2["books"]], [2, 3, 1])

            # 3. Field-specific search (field=authors, q=Elena)
            rd3 = types.SimpleNamespace(query={"q": "Elena", "field": "authors"}, username="student1", outheaders={})
            res3 = inst_srv.institutional_catalog(ctx, rd3)
            self.assertEqual(rd3.last_query, 'authors:"Elena"')
            self.assertEqual(res3["total"], 1)
            self.assertEqual(res3["books"][0]["id"], 1)

            # 4. Facet filtering (category=tags, value=Computer Science)
            rd4 = types.SimpleNamespace(query={"category": "tags", "value": "Computer Science"}, username="student1", outheaders={})
            res4 = inst_srv.institutional_catalog(ctx, rd4)
            self.assertEqual(res4["total"], 1)
            self.assertEqual(res4["books"][0]["id"], 2)


if __name__ == "__main__":
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(AdminV2ProductionTests)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        if not result.wasSuccessful():
            sys.exit(1)
    finally:
        try:
            TEST_DIR.cleanup()
        except Exception:
            pass
