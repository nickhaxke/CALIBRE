"""
P0 Acceptance & Regression Test Suite for Calibre Institutional
Validates:
1. Bug 1: Content Server starts cleanly without imgsrc/srv/generate.py or develop compilation.
2. Bug 2: Library creation/selection outside C:\\dev, persistence across restart, zero dev paths.
3. Bug 3: Server controls, adding book in desktop library -> visible in browser catalogue & portal.
4. Total execution in isolated temporary directory without referencing C:\\dev development fixtures.
"""

import os
import sys
import time
import json
import shutil
import tempfile
import unittest
import subprocess
import urllib.request
import urllib.error

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CALIBRE_RUNTIME_BIN = os.path.expandvars(r"%LOCALAPPDATA%\Programs\CalibreInstitutional\calibre")
if not (os.path.isdir(CALIBRE_RUNTIME_BIN) and os.path.isfile(os.path.join(CALIBRE_RUNTIME_BIN, "calibredb.exe"))):
    CALIBRE_RUNTIME_BIN = os.path.join(PROJECT_ROOT, "test-environment", "installed-app", "calibre")
if not (os.path.isdir(CALIBRE_RUNTIME_BIN) and os.path.isfile(os.path.join(CALIBRE_RUNTIME_BIN, "calibredb.exe"))):
    CALIBRE_RUNTIME_BIN = r"C:\Program Files\CalibreInstitutional\calibre"

CALIBRE_DEBUG = os.path.join(CALIBRE_RUNTIME_BIN, "calibre-debug.exe")
CALIBRE_DB = os.path.join(CALIBRE_RUNTIME_BIN, "calibredb.exe")
CALIBRE_SERVER = os.path.join(CALIBRE_RUNTIME_BIN, "calibre-server.exe")

class TestP0InstallerAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Create fully isolated directory OUTSIDE C:\dev (using Windows TEMP)
        cls.isolated_root = tempfile.mkdtemp(prefix="ci_iso_")
        cls.app_dir = os.path.join(cls.isolated_root, "app")
        cls.config_dir = os.path.join(cls.isolated_root, "cfg")
        cls.desktop_config = os.path.join(cls.isolated_root, "d_cfg")
        cls.cache_dir = os.path.join(cls.isolated_root, "cache")
        cls.library_dir = os.path.join(cls.isolated_root, "lib")

        os.makedirs(cls.config_dir, exist_ok=True)
        os.makedirs(cls.desktop_config, exist_ok=True)
        os.makedirs(cls.cache_dir, exist_ok=True)
        os.makedirs(cls.library_dir, exist_ok=True)

        # 2. Copy source and customization as the installer would lay them out in {app}
        cls.app_src = os.path.join(cls.app_dir, "src")
        cls.app_custom = os.path.join(cls.app_dir, "customization")
        os.makedirs(cls.app_dir, exist_ok=True)

        shutil.copytree(
            os.path.join(PROJECT_ROOT, "upstream", "calibre", "src"),
            cls.app_src,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("*.pyc", "__pycache__", ".git*")
        )
        shutil.copytree(
            os.path.join(PROJECT_ROOT, "customization"),
            cls.app_custom,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("*.pyc", "__pycache__", ".git*")
        )

        # 3. Create isolated test library with sample metadata.db & book files
        import sqlite3
        db_path = os.path.join(cls.library_dir, "metadata.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.executescript("""
            CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, sort TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, pubdate TEXT DEFAULT CURRENT_TIMESTAMP, series_index REAL DEFAULT 1.0, author_sort TEXT, isbn TEXT DEFAULT '', lccn TEXT DEFAULT '', path TEXT NOT NULL DEFAULT '', flags INTEGER DEFAULT 1, uuid TEXT DEFAULT 'uuid-1', has_cover BOOL DEFAULT 0, last_modified TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE authors (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, sort TEXT);
            CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY AUTOINCREMENT, book INTEGER NOT NULL, author INTEGER NOT NULL);
            CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
            CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY AUTOINCREMENT, book INTEGER NOT NULL, tag INTEGER NOT NULL);
            CREATE TABLE publishers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, sort TEXT);
            CREATE TABLE books_publishers_link (id INTEGER PRIMARY KEY AUTOINCREMENT, book INTEGER NOT NULL, publisher INTEGER NOT NULL);
            CREATE TABLE series (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, sort TEXT);
            CREATE TABLE books_series_link (id INTEGER PRIMARY KEY AUTOINCREMENT, book INTEGER NOT NULL, series INTEGER NOT NULL);
            CREATE TABLE data (id INTEGER PRIMARY KEY AUTOINCREMENT, book INTEGER NOT NULL, format TEXT NOT NULL, uncompressed_size INTEGER DEFAULT 1024, name TEXT NOT NULL);
        """)
        author = "Dr. Marcus Vance"
        title = "Principles of Modern Pathology"
        rel_path = f"{author}/{title} (1)"
        book_folder = os.path.join(cls.library_dir, author, f"{title} (1)")
        os.makedirs(book_folder, exist_ok=True)
        book_file = os.path.join(book_folder, f"{title}.pdf")
        with open(book_file, "wb") as f:
            f.write(b"%PDF-1.4 sample content for principles of modern pathology")
        cur.execute("INSERT INTO books (id, title, sort, author_sort, path, has_cover) VALUES (1, ?, ?, ?, ?, 0)", (title, title, author, rel_path))
        cur.execute("INSERT INTO authors (id, name, sort) VALUES (1, ?, ?)", (author, author))
        cur.execute("INSERT INTO books_authors_link (book, author) VALUES (1, 1)")
        cur.execute("INSERT INTO data (book, format, uncompressed_size, name) VALUES (1, 'PDF', ?, ?)", (os.path.getsize(book_file), title))
        conn.commit()
        conn.close()

        # 4. Prepare base environment matching launcher
        cls.base_env = os.environ.copy()
        cls.base_env["CALIBRE_DEVELOP_FROM"] = cls.app_src
        cls.base_env["CALIBRE_DEVELOP_MODE"] = "0"
        cls.base_env["CALIBRE_OVERRIDE_DEVELOP_MODE"] = "0"
        cls.base_env["CALIBRE_INSTITUTIONAL_PRODUCTION"] = "1"
        cls.base_env["CALIBRE_INSTITUTIONAL_HOME"] = cls.app_dir
        cls.base_env["CALIBRE_INSTITUTIONAL_CONFIG_DIR"] = cls.config_dir
        cls.base_env["CALIBRE_CONFIG_DIRECTORY"] = cls.desktop_config
        cls.base_env["CALIBRE_CACHE_DIRECTORY"] = cls.cache_dir
        cls.base_env["CALIBRE_SERVER_BIN"] = CALIBRE_SERVER
        cls.base_env["CALIBRE_DEBUG_BIN"] = CALIBRE_DEBUG

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.isolated_root, ignore_errors=True)

    def test_01_bug1_content_server_starts_without_generate_py_crash(self):
        """Bug 1: Verify Content Server does not trigger live compilation or request imgsrc/srv/generate.py."""
        test_code = """
import sys, time
from calibre.constants import is_running_from_develop
assert not is_running_from_develop, f"is_running_from_develop must be False, got {is_running_from_develop}"

from calibre.srv.embedded import Server
def notify(x): pass
s = Server({}, notify)
s.opts.port = 18095
s.opts.listen_on = "127.0.0.1"
s.start()
time.sleep(1)
running = s.is_running
err = s.exception
s.stop()
s.exit()

if err is not None:
    print(f"SERVER_START_EXCEPTION: {err}")
    sys.exit(1)
if not running:
    print("SERVER_NOT_RUNNING")
    sys.exit(1)
print("BUG1_CONTENT_SERVER_SUCCESS")
"""
        proc = subprocess.run(
            [CALIBRE_DEBUG, "-c", test_code],
            env=self.base_env,
            capture_output=True,
            text=True
        )
        self.assertEqual(proc.returncode, 0, f"Embedded Content Server failed to start:\n{proc.stderr}\n{proc.stdout}")
        self.assertIn("BUG1_CONTENT_SERVER_SUCCESS", proc.stdout)

    def test_02_bug2_library_selection_and_persistence_outside_c_dev(self):
        """Bug 2: Verify first-run wizard saves external library and settings, persisting across reopens with no C:\\dev."""
        backend_dir = os.path.join(self.app_dir, "customization", "backend")
        sys.path.insert(0, backend_dir)
        from config_manager import ConfigManager
        from calibre_user_manager import CalibreUserManager

        db_path = os.path.join(self.config_dir, "institutional_config.sqlite")
        cm = ConfigManager(db_path=db_path)

        # 1. Fresh database starts with setup_completed == False
        self.assertFalse(cm.is_setup_completed(), "Fresh install must require setup")

        # 2. Simulate FirstRunDialog completing setup with our isolated external library
        cm.update_institution_settings(
            name="St. Jude Medical University",
            short_name="SJMU",
            library_title="St. Jude Medical Digital Library",
            primary_color="#0d9488",
            actor="FirstRunDialog"
        )
        cm.add_library(
            display_name="St. Jude Medical Library",
            path=self.library_dir,
            is_default=True,
            is_active=True,
            actor="FirstRunDialog"
        )
        user_mgr = CalibreUserManager(
            userdb_path=os.path.join(self.config_dir, "server-users.sqlite"),
            calibre_bin=CALIBRE_SERVER,
            config_manager=cm
        )
        user_mgr.add_user(
            username="med_admin",
            password="MedAdminPassword2026!",
            role="Administrator",
            full_name="St. Jude Administrator",
            actor="FirstRunDialog"
        )
        cm.mark_setup_completed(True, actor="FirstRunDialog")

        # 3. Verify persistence across reopen (new ConfigManager instance)
        cm_reopened = ConfigManager(db_path=db_path)
        self.assertTrue(cm_reopened.is_setup_completed())
        inst = cm_reopened.get_institution_settings()
        self.assertEqual(inst.get("short_name"), "SJMU")
        self.assertEqual(inst.get("primary_color"), "#0d9488")

        active_libs = cm_reopened.get_active_libraries()
        self.assertEqual(len(active_libs), 1)
        self.assertEqual(os.path.normcase(os.path.abspath(active_libs[0]["path"])),
                         os.path.normcase(os.path.abspath(self.library_dir)))

        # 4. CRITICAL: Ensure NO hardcoded dev paths exist in the saved configuration
        self.assertNotIn("c:\\dev", os.path.normcase(active_libs[0]["path"]))
        self.assertNotIn(".demo", os.path.normcase(active_libs[0]["path"]))

    def test_03_bug3_backend_supervisor_and_gateway_web_workflow(self):
        """Bug 3: Test backend supervisor argument construction, gateway boot, login, and catalog reading."""
        backend_dir = os.path.join(self.app_dir, "customization", "backend")
        sys.path.insert(0, backend_dir)
        from config_manager import ConfigManager
        from backend_supervisor import BackendSupervisor

        db_path = os.path.join(self.config_dir, "institutional_config.sqlite")
        cm = ConfigManager(db_path=db_path)

        # 1. Verify backend supervisor command construction with external library path
        sup = BackendSupervisor(
            config_manager=cm,
            port=18088,
            host="127.0.0.1",
            calibre_bin=CALIBRE_SERVER,
            userdb_path=os.path.join(self.config_dir, "server-users.sqlite")
        )
        cmd_args = sup.build_command_args()
        self.assertIn(os.path.abspath(self.library_dir), [os.path.abspath(a) for a in cmd_args])
        for arg in cmd_args:
            self.assertNotIn("c:\\dev", os.path.normcase(str(arg)))
            self.assertNotIn(".demo", os.path.normcase(str(arg)))

        # 2. Write isolated gateway_config.json
        gw_cfg_path = os.path.join(self.config_dir, "gateway_config.json")
        with open(gw_cfg_path, "w", encoding="utf-8") as f:
            json.dump({
                "gateway_host": "127.0.0.1",
                "gateway_port": 18085,
                "calibre_backend_url": "http://127.0.0.1:18088/calibre",
                "session_cookie_name": "inst_session_id",
                "session_timeout_seconds": 28800,
                "enforce_https": False
            }, f, indent=2)

        gateway_script = os.path.join(self.app_dir, "customization", "backend", "gateway_server.py")
        gw_env = self.base_env.copy()
        gw_env["CALIBRE_INSTITUTIONAL_GATEWAY_CONFIG"] = gw_cfg_path

        # 3. Launch gateway in background process (it will start the backend supervisor itself)
        gw_proc = subprocess.Popen(
            [CALIBRE_DEBUG, "-e", gateway_script],
            cwd=self.app_dir,
            env=gw_env
        )

        try:
            # Wait for gateway to respond
            gateway_ready = False
            for _ in range(25):
                time.sleep(0.5)
                try:
                    with urllib.request.urlopen("http://127.0.0.1:18085/api/auth/status", timeout=1) as resp:
                        if resp.status == 200:
                            gateway_ready = True
                            break
                except Exception:
                    pass

            self.assertTrue(gateway_ready, "Gateway server did not become responsive on port 18085")

            # 4. Check landing page has our institution branding
            with urllib.request.urlopen("http://127.0.0.1:18085/", timeout=3) as resp:
                html = resp.read().decode("utf-8")
                self.assertIn("St. Jude Medical University", html)
                self.assertIn("SJMU", html)

            # 5. Authenticate as med_admin
            login_data = json.dumps({
                "username": "med_admin",
                "password": "MedAdminPassword2026!"
            }).encode("utf-8")
            login_req = urllib.request.Request(
                "http://127.0.0.1:18085/api/auth/login",
                data=login_data,
                headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:18085"}
            )
            with urllib.request.urlopen(login_req, timeout=3) as resp:
                self.assertEqual(resp.status, 200)
                cookie = resp.headers.get("Set-Cookie")
                self.assertIsNotNone(cookie)

            # 6. Query catalog and verify our newly added book is present!
            catalog_req = urllib.request.Request("http://127.0.0.1:18085/api/catalog")
            catalog_req.add_header("Cookie", cookie.split(";")[0])
            with urllib.request.urlopen(catalog_req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                raw_body = resp.read().decode("utf-8")
                books = json.loads(raw_body)
                if len(books) == 0:
                    print(f"DEBUG: Empty catalog response. Checking library_dir={self.library_dir}")
                    print(f"DEBUG: metadata.db exists? {os.path.isfile(os.path.join(self.library_dir, 'metadata.db'))}")
                    print(f"DEBUG: raw_body={raw_body}")
                self.assertGreaterEqual(len(books), 1)
                book_titles = [b.get("title") for b in books]
                self.assertIn("Principles of Modern Pathology", book_titles)

        finally:
            gw_proc.terminate()
            try:
                gw_proc.wait(timeout=3)
            except Exception:
                gw_proc.kill()
            # Clean up backend
            pid_file = os.path.join(self.config_dir, "calibre_backend.pid")
            if os.path.isfile(pid_file):
                try:
                    with open(pid_file, "r") as pf:
                        bpid = int(pf.read().strip())
                    subprocess.run(["taskkill", "/F", "/PID", str(bpid)], capture_output=True)
                except Exception:
                    pass

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestP0InstallerAcceptance)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
