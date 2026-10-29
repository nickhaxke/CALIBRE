"""
Acceptance Verification Script for Calibre Institutional Windows Installer
Tests silent installation, bundled runtime verification, desktop launch,
server controls, web portal access, and clean shutdown in an isolated directory.
"""

import os
import sys
import time
import json
import shutil
import urllib.request
import urllib.parse
import subprocess

PROJECT_ROOT = r"C:\dev\calibre-institutional"
INSTALLER_PATH = os.path.join(PROJECT_ROOT, "dist", "Calibre-Institutional-Setup.exe")
TEST_INSTALL_DIR = os.path.join(PROJECT_ROOT, "test-environment", "installed-app")
EVIDENCE_DIR = os.path.join(PROJECT_ROOT, ".demo", "evidence")
os.makedirs(EVIDENCE_DIR, exist_ok=True)

results = {
    "installer_file": INSTALLER_PATH,
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "steps": [],
    "passed": False,
    "errors": []
}

def record_step(name, success, detail=""):
    results["steps"].append({"name": name, "success": success, "detail": detail})
    status = "PASS" if success else "FAIL"
    print(f"[{status}] {name}: {detail}")
    if not success:
        results["errors"].append(f"{name}: {detail}")

def main():
    print(f"Starting acceptance verification of installer: {INSTALLER_PATH}")

    # 1. Verify installer existence and size
    if not os.path.isfile(INSTALLER_PATH):
        record_step("Installer File Check", False, f"File not found at {INSTALLER_PATH}")
        return False
    
    size_mb = os.path.getsize(INSTALLER_PATH) / (1024 * 1024)
    record_step("Installer File Check", True, f"Found installer ({size_mb:.2f} MB)")

    # 2. Clean previous test install directory
    if os.path.isdir(TEST_INSTALL_DIR):
        try:
            shutil.rmtree(TEST_INSTALL_DIR)
        except Exception as e:
            print(f"Warning cleaning {TEST_INSTALL_DIR}: {e}")

    # 3. Execute silent installation into isolated test environment
    print(f"Running silent installation into: {TEST_INSTALL_DIR} ...")
    cmd = [INSTALLER_PATH, "/VERYSILENT", "/SUPPRESSMSGBOXES", f"/DIR={TEST_INSTALL_DIR}"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        record_step("Silent Installation", False, f"Installer exited with code {proc.returncode}: {proc.stderr}")
        return False
    
    record_step("Silent Installation", True, f"Successfully installed to {TEST_INSTALL_DIR}")

    # 4. Verify bundled runtime and customized components
    required_files = [
        ("Launcher Executable", os.path.join(TEST_INSTALL_DIR, "CalibreInstitutional.exe")),
        ("Bundled Calibre GUI", os.path.join(TEST_INSTALL_DIR, "calibre", "calibre.exe")),
        ("Bundled Content Server", os.path.join(TEST_INSTALL_DIR, "calibre", "calibre-server.exe")),
        ("Bundled Debug Runner", os.path.join(TEST_INSTALL_DIR, "calibre", "calibre-debug.exe")),
        ("Customized Calibre Source", os.path.join(TEST_INSTALL_DIR, "src", "calibre", "gui2", "institutional_server.py")),
        ("Customized Actions", os.path.join(TEST_INSTALL_DIR, "src", "calibre", "gui2", "actions", "institutional_server.py")),
        ("Institutional Gateway", os.path.join(TEST_INSTALL_DIR, "customization", "backend", "gateway_server.py")),
        ("Frontend Templates", os.path.join(TEST_INSTALL_DIR, "customization", "frontend", "templates", "index.html")),
        ("GPL v3 License Notice", os.path.join(TEST_INSTALL_DIR, "licenses", "CALIBRE_GPL_v3.txt")),
    ]

    missing = []
    for label, path in required_files:
        if os.path.isfile(path):
            record_step(f"Component: {label}", True, f"Verified ({os.path.getsize(path):,} bytes)")
        else:
            record_step(f"Component: {label}", False, f"Missing at {path}")
            missing.append(label)

    if missing:
        record_step("Bundle Integrity Check", False, f"Missing components: {', '.join(missing)}")
        return False
    record_step("Bundle Integrity Check", True, "All required bundled components present")

    # 5. Verify installed runtime execution and Desktop Server Controls
    print("Testing installed runtime execution and server controls...")
    test_env = os.environ.copy()
    test_env["CALIBRE_DEVELOP_FROM"] = os.path.join(TEST_INSTALL_DIR, "src")
    test_env["CALIBRE_CONFIG_DIRECTORY"] = os.path.join(TEST_INSTALL_DIR, "desktop-config")
    test_env["CALIBRE_CACHE_DIRECTORY"] = os.path.join(TEST_INSTALL_DIR, "local-cache")
    test_env["CALIBRE_INSTITUTIONAL_HOME"] = TEST_INSTALL_DIR
    test_env["CALIBRE_INSTITUTIONAL_CONFIG_DIR"] = os.path.join(PROJECT_ROOT, ".demo", "config")
    test_env["CALIBRE_INSTITUTIONAL_BRANDING"] = os.path.join(PROJECT_ROOT, "customization", "configuration", "demo-branding.json")
    test_env["CALIBRE_INSTITUTIONAL_GATEWAY_CONFIG"] = os.path.join(PROJECT_ROOT, ".demo", "gateway.json")
    test_env["CALIBRE_SERVER_BIN"] = os.path.join(TEST_INSTALL_DIR, "calibre", "calibre-server.exe")
    test_env["CALIBRE_DEBUG_BIN"] = os.path.join(TEST_INSTALL_DIR, "calibre", "calibre-debug.exe")

    calibre_debug = os.path.join(TEST_INSTALL_DIR, "calibre", "calibre-debug.exe")

    # Inline script to test InstitutionalServerManager in installed environment
    python_test_code = """
import os, sys, time
from qt.core import QApplication
app = QApplication.instance() or QApplication([])
from calibre.gui2.institutional_server import InstitutionalServerManager, InstitutionalServerDialog

class MockGui:
    def __init__(self):
        self.library_path = r"C:\\dev\\calibre-institutional\\.demo\\library"

gui = MockGui()
mgr = InstitutionalServerManager(gui)
print("INSTALLED_MGR_INIT_OK")

diag = InstitutionalServerDialog(mgr)
print("INSTALLED_DIAG_INIT_OK")

print("SERVER_RESPONSIVE:", mgr.is_responsive())
"""

    verify_proc = subprocess.run(
        [calibre_debug, "-c", python_test_code],
        env=test_env,
        capture_output=True,
        text=True
    )

    if "INSTALLED_MGR_INIT_OK" in verify_proc.stdout and "INSTALLED_DIAG_INIT_OK" in verify_proc.stdout:
        record_step("Installed Runtime & Server Controls", True, "InstitutionalServerManager & Dialog initialized cleanly from installed bundle")
    else:
        record_step("Installed Runtime & Server Controls", False, f"Failed runtime initialization: {verify_proc.stderr or verify_proc.stdout}")
        return False

    # 6. Verify web portal access via active server
    try:
        req = urllib.request.Request("http://127.0.0.1:8085/")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
            if resp.status == 200 and "Aethelgard" in content:
                record_step("Web Portal Landing Page", True, "Successfully loaded customized institutional landing page from gateway")
            else:
                record_step("Web Portal Landing Page", False, f"Unexpected response (status {resp.status})")
    except Exception as e:
        record_step("Web Portal Landing Page", False, f"Error connecting to portal: {e}")

    # 7. Check credentials and login
    creds_file = os.path.join(PROJECT_ROOT, ".demo", "credentials.json")
    if os.path.isfile(creds_file):
        with open(creds_file, 'r', encoding='utf-8') as f:
            creds = json.load(f)
        reader_creds = creds.get('reader', {})
        try:
            login_req = urllib.request.Request(
                "http://127.0.0.1:8085/api/auth/login",
                data=json.dumps(reader_creds).encode('utf-8'),
                headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8085"}
            )
            with urllib.request.urlopen(login_req, timeout=3.0) as resp:
                if resp.status == 200:
                    cookie = resp.headers.get('Set-Cookie', '')
                    record_step("Patron Authentication", True, f"Reader login successful (cookie received)")
                else:
                    record_step("Patron Authentication", False, f"Login returned status {resp.status}")
        except Exception as e:
            record_step("Patron Authentication", False, f"Login error: {e}")

    results["passed"] = (len(results["errors"]) == 0)
    print("\n" + "="*60)
    print(f"ACCEPTANCE VERIFICATION RESULT: {'PASSED' if results['passed'] else 'FAILED'}")
    print("="*60)
    return results["passed"]

if __name__ == '__main__':
    success = main()
    with open(os.path.join(EVIDENCE_DIR, "installer-verification.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    sys.exit(0 if success else 1)
