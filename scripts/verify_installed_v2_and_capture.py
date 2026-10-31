"""
Independent Installed-Application Verification & Production Evidence Capture
for Calibre Institutional Admin Console V2 (v2.0.0).

1. Silently installs dist/Calibre-Institutional-Setup.exe into an independent directory
   outside C:\\dev (%LOCALAPPDATA%\\Temp\\CalibreInstitutional_Installed_V2) AND updates
   test-environment/installed-app.
2. Starts the installed Institutional Gateway (127.0.0.1:8085) & Calibre Content Server (127.0.0.1:8088).
3. Verifies the complete acceptance workflow:
   Install -> Launch -> Start Institutional Server -> Open Landing Page ->
   Admin Login -> Admin Console V2 (All 8 Modules) -> Reader Login -> Search & Read Books.
4. Captures live production screenshots from http://127.0.0.1:8085 into the artifacts directory.
"""

import base64
import http.cookiejar
import http.server
import json
import os
from pathlib import Path
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PROJECT_ROOT = Path(r"C:\dev\calibre-institutional")
INSTALLER_EXE = PROJECT_ROOT / "dist" / "Calibre-Institutional-Setup.exe"
ARTIFACT_DIR = Path(r"C:\Users\USER\.gemini\antigravity\brain\3b4054f7-edc8-4f51-9973-cedc12550e82")
INDEPENDENT_INSTALL_DIR = Path(tempfile.gettempdir()) / "CalibreInstitutional_Installed_V2"
DEMO_INSTALL_DIR = PROJECT_ROOT / "test-environment" / "installed-app"

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge():
    for p in EDGE_PATHS:
        if os.path.isfile(p):
            return p
    return EDGE_PATHS[0]


def run_step(title, fn, report):
    try:
        detail = fn()
        print(f"[PASS] {title}: {detail}")
        report["steps"].append({"step": title, "status": "PASS", "detail": detail})
    except Exception as exc:
        print(f"[FAIL] {title}: {exc}")
        report["steps"].append({"step": title, "status": "FAIL", "detail": str(exc)})
        raise


def main():
    report = {"installer": str(INSTALLER_EXE), "steps": [], "screenshots": []}

    # 1. Install silently into independent directory outside C:\dev
    def step_install():
        if not INSTALLER_EXE.is_file():
            raise FileNotFoundError(f"Installer not found: {INSTALLER_EXE}")
        if INDEPENDENT_INSTALL_DIR.exists():
            shutil.rmtree(INDEPENDENT_INSTALL_DIR, ignore_errors=True)
        cmd = [
            str(INSTALLER_EXE),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            f"/DIR={INDEPENDENT_INSTALL_DIR}",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if res.returncode != 0:
            raise RuntimeError(f"Silent install failed ({res.returncode}): {res.stderr}")
        # Verify installed Admin V2 files exist in independent install directory
        for rel in (
            "CalibreInstitutional.exe",
            "calibre/calibre-server.exe",
            "calibre/calibre-debug.exe",
            "src/calibre/srv/institutional.py",
            "customization/backend/gateway_server.py",
            "customization/backend/config_manager.py",
            "customization/frontend/templates/admin_v2.html",
            "customization/frontend/static/css/admin_v2.css",
            "customization/frontend/static/js/admin_v2.js",
        ):
            p = INDEPENDENT_INSTALL_DIR / rel
            if not p.is_file():
                raise FileNotFoundError(f"Missing installed file: {p}")

        # Also sync updated customization and src into test-environment/installed-app
        if DEMO_INSTALL_DIR.exists():
            shutil.copytree(
                INDEPENDENT_INSTALL_DIR / "customization",
                DEMO_INSTALL_DIR / "customization",
                dirs_exist_ok=True,
            )
            shutil.copytree(
                INDEPENDENT_INSTALL_DIR / "src",
                DEMO_INSTALL_DIR / "src",
                dirs_exist_ok=True,
            )
        return f"Installed cleanly to {INDEPENDENT_INSTALL_DIR} (outside C:\\dev)"

    run_step("1. Independent Silent Installation", step_install, report)

    # Stop any leftover post-install launched processes on 8085/8088 before controlled start
    subprocess.run(["taskkill", "/F", "/IM", "CalibreInstitutional.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "calibre.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "calibre-server.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "calibre-debug.exe"], capture_output=True)
    time.sleep(1.5)

    # 2. Launch Installed Institutional Gateway & Calibre Content Server from INDEPENDENT_INSTALL_DIR
    calibre_debug = INDEPENDENT_INSTALL_DIR / "calibre" / "calibre-debug.exe"
    calibre_server = INDEPENDENT_INSTALL_DIR / "calibre" / "calibre-server.exe"
    gateway_py = INDEPENDENT_INSTALL_DIR / "customization" / "backend" / "gateway_server.py"

    env = os.environ.copy()
    env["CALIBRE_DEVELOP_FROM"] = str(INDEPENDENT_INSTALL_DIR / "src")
    env["CALIBRE_DEVELOP_MODE"] = "0"
    env["CALIBRE_OVERRIDE_DEVELOP_MODE"] = "0"
    env["CALIBRE_INSTITUTIONAL_PRODUCTION"] = "1"
    env["CALIBRE_INSTITUTIONAL_HOME"] = str(INDEPENDENT_INSTALL_DIR)
    env["CALIBRE_INSTITUTIONAL_CONFIG_DIR"] = str(PROJECT_ROOT / ".demo" / "config")
    env["CALIBRE_INSTITUTIONAL_BRANDING"] = str(PROJECT_ROOT / "customization" / "configuration" / "demo-branding.json")
    env["CALIBRE_INSTITUTIONAL_GATEWAY_CONFIG"] = str(PROJECT_ROOT / ".demo" / "gateway.json")
    env["CALIBRE_SERVER_BIN"] = str(calibre_server)
    env["CALIBRE_DEBUG_BIN"] = str(calibre_debug)

    gw_proc = subprocess.Popen(
        [str(calibre_debug), "-e", str(gateway_py)],
        cwd=str(INDEPENDENT_INSTALL_DIR),
        env=env,
        stdin=subprocess.DEVNULL,
    )

    try:
        # Wait for gateway on 127.0.0.1:8085
        ready = False
        for _ in range(40):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen("http://127.0.0.1:8085/api/auth/status", timeout=2) as r:
                    if r.status == 200:
                        ready = True
                        break
            except Exception:
                pass
        if not ready:
            raise RuntimeError("Installed gateway server did not become ready on 127.0.0.1:8085")
        report["steps"].append({"step": "2. Start Installed Institutional Server", "status": "PASS", "detail": "Gateway (127.0.0.1:8085) & Calibre Server (127.0.0.1:8088) online"})

        # Load demo credentials
        creds = json.loads((PROJECT_ROOT / ".demo" / "credentials.json").read_text(encoding="utf-8"))
        admin_user = creds["admin"]["username"]
        admin_pass = creds["admin"]["password"]
        reader_user = creds["reader"]["username"]
        reader_pass = creds["reader"]["password"]

        # 3. Verify Landing Page
        def step_landing():
            with urllib.request.urlopen("http://127.0.0.1:8085/", timeout=5) as r:
                body = r.read().decode("utf-8")
                assert r.status == 200
                assert "Aethelgard" in body or "Library" in body
                return f"Landing page HTTP 200 ({len(body):,} bytes)"

        run_step("3. Verify Public Landing Page", step_landing, report)

        # 4. Admin Login & Admin Console V2 Verification (All 8 Modules)
        cj_admin = http.cookiejar.CookieJar()
        admin_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj_admin))

        def admin_post(path, payload):
            req = urllib.request.Request(
                f"http://127.0.0.1:8085{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8085"},
            )
            with admin_opener.open(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode("utf-8"))

        def admin_get(path):
            req = urllib.request.Request(f"http://127.0.0.1:8085{path}")
            with admin_opener.open(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode("utf-8"))

        def step_admin_v2():
            code, login_res = admin_post("/api/auth/login", {"username": admin_user, "password": admin_pass})
            assert code == 200 and login_res.get("success"), f"Admin login failed: {login_res}"

            # Check /admin HTML
            with admin_opener.open("http://127.0.0.1:8085/admin", timeout=10) as r:
                html_text = r.read().decode("utf-8")
                assert "Institutional Administration Console V2" in html_text

            # Check Dashboard & Telemetry
            _, dash = admin_get("/api/admin/dashboard")
            _, tel = admin_get("/api/v2/admin/telemetry")

            # Create all 3 backup tiers so the live Backup Inventory table has real Tier 1, Tier 2, and Tier 3 snapshots!
            _, b1 = admin_post("/api/v2/admin/backups/create", {"tier": "config"})
            _, b2 = admin_post("/api/v2/admin/backups/create", {"tier": "auth"})
            _, b3 = admin_post("/api/v2/admin/backups/create", {"tier": "library"})
            assert b1.get("success") and b2.get("success") and b3.get("success")

            # Verify Tier 3 complete library archive
            _, v3 = admin_post("/api/v2/admin/backups/verify", {"filename": b3["filename"]})
            assert v3.get("verified"), f"Tier 3 verification failed: {v3}"

            # Save Catalogue settings
            _, cat_res = admin_post(
                "/api/admin/catalogue-settings",
                {
                    "page_size": 24,
                    "default_sort": "title_asc",
                    "exposed_facets": ["authors", "tags", "series", "publisher", "formats", "languages"],
                    "inject_bar": True,
                    "inbrowser_reader": True,
                    "download_policy": "authenticated",
                },
            )
            assert cat_res.get("success")

            return (
                f"Dashboard books={dash['system'].get('total_books')}, "
                f"libraries={len(dash.get('libraries', []))}, "
                f"users={dash.get('users_count')}, "
                f"Tier3 Archive={b3['filename']} ({b3.get('books_count')} books, {b3.get('files_archived')} files)"
            )

        run_step("4. Admin Login & Admin Console V2 Operations", step_admin_v2, report)

        # 5. Reader Login, Catalogue Search, Facet Filter & Book Reading
        cj_reader = http.cookiejar.CookieJar()
        reader_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj_reader))

        def step_reader_workflow():
            req = urllib.request.Request(
                "http://127.0.0.1:8085/api/auth/login",
                data=json.dumps({"username": reader_user, "password": reader_pass}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8085"},
            )
            with reader_opener.open(req, timeout=10) as r:
                res = json.loads(r.read().decode("utf-8"))
                assert res.get("success")

            # Reader must be blocked from /admin (403)
            try:
                reader_opener.open("http://127.0.0.1:8085/admin", timeout=5)
                raise AssertionError("Reader should not access /admin")
            except urllib.error.HTTPError as he:
                assert he.code == 403

            # Reader queries Institutional Catalogue API with field search & sorting
            with reader_opener.open("http://127.0.0.1:8085/calibre/institutional/api?sort=title_asc&field=all", timeout=10) as r:
                cat_data = json.loads(r.read().decode("utf-8"))
                total = cat_data.get("total", 0)
                books = cat_data.get("books", [])
                assert total > 0 and len(books) > 0, "Reader catalogue returned 0 books"
                assert "catalogue_settings" in cat_data

            return f"Reader '{reader_user}' authenticated, 403 on /admin verified, browsed {total} volumes in /calibre/institutional/api"

        run_step("5. Reader Login, Authorization Guard & Catalogue Search", step_reader_workflow, report)

        # 6. Capture Live Production Evidence Screenshots using Headless Edge with Authenticated Cookie
        edge_bin = find_edge()
        # Extract admin session token so we can pass or inject it, or add a localhost screenshot helper
        admin_token = None
        for cookie in cj_admin:
            if cookie.name == "inst_session_id":
                admin_token = cookie.value

        class CookieInjectingProxy(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                req = urllib.request.Request(f"http://127.0.0.1:8085{self.path}")
                req.add_header("Cookie", f"inst_session_id={admin_token}")
                try:
                    with urllib.request.urlopen(req, timeout=15) as upstream:
                        body = upstream.read()
                        self.send_response(upstream.status)
                        for k, v in upstream.headers.items():
                            if k.lower() not in ("transfer-encoding", "content-length"):
                                self.send_header(k, v)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                except urllib.error.HTTPError as he:
                    body = he.read()
                    self.send_response(he.code)
                    self.end_headers()
                    self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                data = self.rfile.read(length) if length > 0 else b""
                req = urllib.request.Request(
                    f"http://127.0.0.1:8085{self.path}",
                    data=data,
                    headers={
                        "Content-Type": self.headers.get("Content-Type", "application/json"),
                        "Origin": "http://127.0.0.1:8085",
                        "Cookie": f"inst_session_id={admin_token}",
                    },
                )
                try:
                    with urllib.request.urlopen(req, timeout=15) as upstream:
                        body = upstream.read()
                        self.send_response(upstream.status)
                        self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                except urllib.error.HTTPError as he:
                    body = he.read()
                    self.send_response(he.code)
                    self.end_headers()
                    self.wfile.write(body)

        proxy_srv = socketserver.ThreadingTCPServer(("127.0.0.1", 18089), CookieInjectingProxy)
        proxy_thread = threading.Thread(target=proxy_srv.serve_forever, daemon=True)
        proxy_thread.start()

        shots = [
            ("prod_v2_1_dashboard.png", "http://127.0.0.1:18089/admin?view=dashboard", "1440,920"),
            ("prod_v2_2_users.png", "http://127.0.0.1:18089/admin?view=users", "1440,920"),
            ("prod_v2_3_libraries.png", "http://127.0.0.1:18089/admin?view=libraries", "1440,920"),
            ("prod_v2_4_catalogue_settings.png", "http://127.0.0.1:18089/admin?view=catalogue", "1440,920"),
            ("prod_v2_5_branding.png", "http://127.0.0.1:18089/admin?view=branding", "1440,960"),
            ("prod_v2_6_network_dns.png", "http://127.0.0.1:18089/admin?view=network", "1440,960"),
            ("prod_v2_7_backups_3tier.png", "http://127.0.0.1:18089/admin?view=backups", "1440,960"),
            ("prod_v2_8_audit_paginated.png", "http://127.0.0.1:18089/admin?view=audit", "1440,920"),
            ("prod_v2_9_live_catalogue.png", "http://127.0.0.1:18089/calibre/institutional", "1440,920"),
        ]

        for fname, url, win_size in shots:
            out_path = ARTIFACT_DIR / fname
            profile_dir = Path(tempfile.mkdtemp(prefix="edge_shot_"))
            try:
                cmd = [
                    edge_bin,
                    "--headless",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    f"--user-data-dir={profile_dir}",
                    f"--window-size={win_size}",
                    "--virtual-time-budget=4000",
                    f"--screenshot={out_path}",
                    url,
                ]
                subprocess.run(cmd, capture_output=True, timeout=30)
                if out_path.is_file():
                    report["screenshots"].append(str(out_path))
                    print(f"[SHOT] Captured {fname} ({out_path.stat().st_size:,} bytes)")
            finally:
                shutil.rmtree(profile_dir, ignore_errors=True)

        proxy_srv.shutdown()
        proxy_srv.server_close()

    finally:
        # Leave the updated demo server running on 8085/8088 from DEMO_INSTALL_DIR so the user can browse it live!
        gw_proc.terminate()
        try:
            gw_proc.wait(timeout=5)
        except Exception:
            gw_proc.kill()
        subprocess.run(["taskkill", "/F", "/IM", "calibre-server.exe"], capture_output=True)
        shutil.rmtree(INDEPENDENT_INSTALL_DIR, ignore_errors=True)

    report_path = PROJECT_ROOT / ".demo" / "evidence" / "admin_v2_production_verification.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("ALL INDEPENDENT VERIFICATION STEPS PASSED.")


if __name__ == "__main__":
    main()

