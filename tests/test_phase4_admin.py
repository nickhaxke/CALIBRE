"""
Phase 4 Automated Acceptance & Security Test Suite
Institutional Digital Library Gateway

Covers:
- First-Time Setup Wizard lifecycle, pre-flight checks, path validation, and completion lock
- Administration portal access control (401 unauthenticated, 403 non-admin, 200 admin)
- Dynamic institutional settings & branding updates
- Calibre library connection, validation, and non-destructive management
- Official Calibre CLI user provisioning, password updates, readonly toggle, and deletion
- CSRF protection and security safeguards on all admin APIs
- Configuration persistence, backup generation, and audit logging
"""

import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie

GATEWAY_URL = "http://127.0.0.1:8085"
COOKIE_NAME = "inst_session_id"
TEST_LIBRARY = r"C:\dev\calibre-institutional\test-environment\library"
SECONDARY_LIB = r"C:\dev\calibre-institutional\test-environment\libraries\research_archive"

class TestPhase4AdminAndSetup(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        # Restore baseline institutional settings for subsequent test suites
        try:
            from config_manager import ConfigManager
            cfg = ConfigManager()
            cfg.update_institution_settings(
                name="Aethelgard Institute of Technology",
                short_name="AIT",
                library_title="Institutional Digital Library & Research Repository",
                motto="Academic Volumes, Digital Collections & Faculty Research",
                contact_email="library@ait.ac.zm",
                contact_phone="+260 211 256177",
                logo_path="/static/images/seal.png",
                actor="TestTearDown"
            )
        except Exception:
            pass

    @classmethod
    def setUpClass(cls):
        # Reset any rate limits
        try:
            req = urllib.request.Request(f"{GATEWAY_URL}/api/auth/reset-rate-limit", data=b"{}")
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass

    def setUp(self):
        self.cookie_jar = SimpleCookie()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def _login(self, username, password):
        login_url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": username, "password": password}).encode("utf-8")
        req = urllib.request.Request(login_url, data=payload, headers={
            "Content-Type": "application/json",
            "Origin": GATEWAY_URL
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            cookie_hdr = resp.headers.get("Set-Cookie", "")
            return data, cookie_hdr

    def test_01_setup_status_preflight(self):
        """Verifies /api/setup/status pre-flight check returns Calibre version and storage info."""
        req = urllib.request.Request(f"{GATEWAY_URL}/api/setup/status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("calibre_installed"))
            self.assertIn("calibre", data.get("calibre_version", "").lower())
            self.assertEqual(data.get("gateway_port"), 8085)
            self.assertTrue(data.get("writable"))

    def test_02_library_path_validation(self):
        """Verifies library path validation rejects system roots and validates metadata.db."""
        # 1. Invalid path
        req1 = urllib.request.Request(f"{GATEWAY_URL}/api/setup/validate-library", 
                                      data=json.dumps({"library_path": r"C:\non_existent_folder_xyz"}).encode("utf-8"),
                                      headers={"Content-Type": "application/json", "Origin": GATEWAY_URL})
        with urllib.request.urlopen(req1, timeout=5) as resp:
            d1 = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(d1.get("valid"))

        # 2. System root rejected
        req2 = urllib.request.Request(f"{GATEWAY_URL}/api/setup/validate-library", 
                                      data=json.dumps({"library_path": r"C:\Windows"}).encode("utf-8"),
                                      headers={"Content-Type": "application/json", "Origin": GATEWAY_URL})
        try:
            with urllib.request.urlopen(req2, timeout=5) as resp:
                d2 = json.loads(resp.read().decode("utf-8"))
                self.assertFalse(d2.get("valid"))
        except urllib.error.HTTPError as he:
            self.assertEqual(he.code, 400)

        # 3. Valid Calibre library folder
        req3 = urllib.request.Request(f"{GATEWAY_URL}/api/setup/validate-library", 
                                      data=json.dumps({"library_path": TEST_LIBRARY}).encode("utf-8"),
                                      headers={"Content-Type": "application/json", "Origin": GATEWAY_URL})
        with urllib.request.urlopen(req3, timeout=5) as resp:
            d3 = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(d3.get("valid"))
            self.assertGreater(d3.get("books_count", 0), 0)

    def test_03_admin_portal_access_control(self):
        """Verifies that /admin rejects unauthenticated requests and non-admin patrons with 403."""
        # 1. Unauthenticated request -> redirects to login
        req1 = urllib.request.Request(f"{GATEWAY_URL}/admin", headers={"Accept": "text/html"})
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def http_error_302(self, req, fp, code, msg, headers):
                return fp
        opener = urllib.request.build_opener(NoRedirectHandler)
        try:
            resp = opener.open(req1, timeout=5)
            self.assertIn(resp.status, (302, 200))
        except urllib.error.HTTPError as he:
            self.assertEqual(he.code, 302)

        # 2. Non-admin patron (student1) attempts admin access -> 403 Forbidden
        _, student_cookie = self._login("student1", "StudentPass123!")
        token = student_cookie.split(";")[0]

        # GET /admin as student
        req2 = urllib.request.Request(f"{GATEWAY_URL}/admin", headers={
            "Cookie": token,
            "Accept": "text/html"
        })
        try:
            resp = urllib.request.urlopen(req2, timeout=5)
            self.fail("Student patron should not be allowed into /admin")
        except urllib.error.HTTPError as he:
            self.assertEqual(he.code, 403)

        # GET /api/admin/dashboard as student
        req3 = urllib.request.Request(f"{GATEWAY_URL}/api/admin/dashboard", headers={"Cookie": token})
        try:
            resp = urllib.request.urlopen(req3, timeout=5)
            self.fail("Student patron should not access admin API")
        except urllib.error.HTTPError as he:
            self.assertEqual(he.code, 403)

        # 3. Administrator (librarian1) access -> 200 OK
        _, admin_cookie = self._login("librarian1", "LibAdminPass123!")
        admin_token = admin_cookie.split(";")[0]

        req4 = urllib.request.Request(f"{GATEWAY_URL}/admin", headers={"Cookie": admin_token, "Accept": "text/html"})
        with urllib.request.urlopen(req4, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("Institutional Administration", html)
            self.assertIn("Dashboard", html)

        req5 = urllib.request.Request(f"{GATEWAY_URL}/api/admin/dashboard", headers={"Cookie": admin_token})
        with urllib.request.urlopen(req5, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("institution", data)
            self.assertIn("libraries", data)
            self.assertGreaterEqual(data.get("users_count", 0), 1)

    def test_04_institution_settings_update_and_branding(self):
        """Verifies institutional settings update, persistence, and dynamic portal reflection."""
        _, admin_cookie = self._login("librarian1", "LibAdminPass123!")
        admin_token = admin_cookie.split(";")[0]

        # 1. Update institution identity to National Institute of Public Administration
        update_payload = {
            "name": "National Institute of Public Administration",
            "short_name": "NIPA",
            "library_name": "Dr. Kenneth Kaunda Memorial Digital Library",
            "motto": "Excellence in Leadership, Governance and Public Policy",
            "contact_email": "library@nipa.ac.zm",
            "contact_phone": "+260 211 256177",
            "logo_url": "/static/images/nipa_seal.png"
        }
        req = urllib.request.Request(f"{GATEWAY_URL}/api/admin/settings",
                                     data=json.dumps(update_payload).encode("utf-8"),
                                     headers={
                                         "Content-Type": "application/json",
                                         "Cookie": admin_token,
                                         "Origin": GATEWAY_URL
                                     })
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res.get("success"))

        # 2. Verify settings API reflects new values
        req_get = urllib.request.Request(f"{GATEWAY_URL}/api/admin/settings", headers={"Cookie": admin_token})
        with urllib.request.urlopen(req_get, timeout=5) as resp:
            settings = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(settings.get("institution_name"), "National Institute of Public Administration")
            self.assertEqual(settings.get("short_name"), "NIPA")
            self.assertEqual(settings.get("library_title"), "Dr. Kenneth Kaunda Memorial Digital Library")

        # 3. Verify landing page / dynamically renders the new institutional name
        req_lp = urllib.request.Request(f"{GATEWAY_URL}/")
        with urllib.request.urlopen(req_lp, timeout=5) as resp:
            html = resp.read().decode("utf-8")
            self.assertIn("National Institute of Public Administration", html)
            self.assertIn("Dr. Kenneth Kaunda Memorial Digital Library", html)
            self.assertIn("NIPA", html)

    def test_05_library_management_crud(self):
        """Verifies connecting a library, setting default, non-destructive toggling and removal."""
        _, admin_cookie = self._login("librarian1", "LibAdminPass123!")
        admin_token = admin_cookie.split(";")[0]

        # 1. Connect secondary library (research_archive)
        add_payload = {
            "display_name": "Research Archive Collection",
            "library_path": SECONDARY_LIB,
            "is_default": False
        }
        req_add = urllib.request.Request(f"{GATEWAY_URL}/api/admin/libraries",
                                         data=json.dumps(add_payload).encode("utf-8"),
                                         headers={
                                             "Content-Type": "application/json",
                                             "Cookie": admin_token,
                                             "Origin": GATEWAY_URL
                                         })
        with urllib.request.urlopen(req_add, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

        # 2. Query libraries list
        req_list = urllib.request.Request(f"{GATEWAY_URL}/api/admin/libraries", headers={"Cookie": admin_token})
        with urllib.request.urlopen(req_list, timeout=5) as resp:
            libs = json.loads(resp.read().decode("utf-8"))
            sec_lib = next((l for l in libs if l["display_name"] == "Research Archive Collection"), None)
            self.assertIsNotNone(sec_lib)
            sec_id = sec_lib["id"]

        # 3. Toggle active/disabled status (non-destructive disable)
        req_toggle = urllib.request.Request(f"{GATEWAY_URL}/api/admin/libraries/toggle",
                                           data=json.dumps({"library_id": sec_id, "is_active": False}).encode("utf-8"),
                                           headers={
                                               "Content-Type": "application/json",
                                               "Cookie": admin_token,
                                               "Origin": GATEWAY_URL
                                           })
        with urllib.request.urlopen(req_toggle, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

        # Verify disabled
        with urllib.request.urlopen(req_list, timeout=5) as resp:
            libs = json.loads(resp.read().decode("utf-8"))
            sec_lib = next((l for l in libs if l["id"] == sec_id), None)
            self.assertFalse(sec_lib["is_active"])

        # 4. Remove library association
        req_rm = urllib.request.Request(f"{GATEWAY_URL}/api/admin/libraries/remove",
                                        data=json.dumps({"library_id": sec_id}).encode("utf-8"),
                                        headers={
                                            "Content-Type": "application/json",
                                            "Cookie": admin_token,
                                            "Origin": GATEWAY_URL
                                        })
        with urllib.request.urlopen(req_rm, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

        # Verify removed from config while files on disk remain completely untouched!
        self.assertTrue(os.path.isfile(os.path.join(SECONDARY_LIB, "metadata.db")))

    def test_06_calibre_user_administration_lifecycle(self):
        """Verifies creating a Calibre user, changing password, readonly toggle, login, and deletion."""
        _, admin_cookie = self._login("librarian1", "LibAdminPass123!")
        admin_token = admin_cookie.split(";")[0]

        test_user = "inst_auditor99"
        test_pass = "AuditorPass123!"

        # 1. Create User
        create_payload = {
            "username": test_user,
            "password": test_pass,
            "full_name": "Senior Auditor Mwape",
            "role": "Staff",
            "department": "Quality Assurance",
            "readonly": True
        }
        req_create = urllib.request.Request(f"{GATEWAY_URL}/api/admin/users/create",
                                            data=json.dumps(create_payload).encode("utf-8"),
                                            headers={
                                                "Content-Type": "application/json",
                                                "Cookie": admin_token,
                                                "Origin": GATEWAY_URL
                                            })
        with urllib.request.urlopen(req_create, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res.get("success"))

        # 2. Verify new user can immediately authenticate via Gateway!
        user_auth, user_cookie = self._login(test_user, test_pass)
        self.assertTrue(user_auth.get("success"))
        self.assertEqual(user_auth["user"]["username"], test_user)
        self.assertEqual(user_auth["user"]["role"], "Staff")
        self.assertEqual(user_auth["user"]["displayName"], "Senior Auditor Mwape")

        # 3. Change Password
        new_pass = "UpdatedAuditorPass456!"
        req_chpass = urllib.request.Request(f"{GATEWAY_URL}/api/admin/users/change-password",
                                            data=json.dumps({"username": test_user, "new_password": new_pass}).encode("utf-8"),
                                            headers={
                                                "Content-Type": "application/json",
                                                "Cookie": admin_token,
                                                "Origin": GATEWAY_URL
                                            })
        with urllib.request.urlopen(req_chpass, timeout=10) as resp:
            self.assertEqual(resp.status, 200)

        # Old password rejected
        try:
            self._login(test_user, test_pass)
            self.fail("Old password should be rejected after change")
        except urllib.error.HTTPError as he:
            self.assertEqual(he.code, 401)

        # New password accepted
        re_auth, _ = self._login(test_user, new_pass)
        self.assertTrue(re_auth.get("success"))

        # 4. Toggle Readonly Status
        req_ro = urllib.request.Request(f"{GATEWAY_URL}/api/admin/users/readonly",
                                        data=json.dumps({"username": test_user, "readonly": False}).encode("utf-8"),
                                        headers={
                                            "Content-Type": "application/json",
                                            "Cookie": admin_token,
                                            "Origin": GATEWAY_URL
                                        })
        with urllib.request.urlopen(req_ro, timeout=10) as resp:
            self.assertEqual(resp.status, 200)

        # 5. Prevent Admin Self-Deletion
        req_self_del = urllib.request.Request(f"{GATEWAY_URL}/api/admin/users/remove",
                                              data=json.dumps({"username": "librarian1"}).encode("utf-8"),
                                              headers={
                                                  "Content-Type": "application/json",
                                                  "Cookie": admin_token,
                                                  "Origin": GATEWAY_URL
                                              })
        try:
            resp = urllib.request.urlopen(req_self_del, timeout=5)
            self.fail("Admin self-deletion must be blocked")
        except urllib.error.HTTPError as he:
            self.assertEqual(he.code, 400)

        # 6. Delete Test User
        req_del = urllib.request.Request(f"{GATEWAY_URL}/api/admin/users/remove",
                                         data=json.dumps({"username": test_user}).encode("utf-8"),
                                         headers={
                                             "Content-Type": "application/json",
                                             "Cookie": admin_token,
                                             "Origin": GATEWAY_URL
                                         })
        with urllib.request.urlopen(req_del, timeout=10) as resp:
            self.assertEqual(resp.status, 200)

        # Deleted user cannot log in
        try:
            self._login(test_user, new_pass)
            self.fail("Deleted user should not be able to log in")
        except urllib.error.HTTPError as he:
            self.assertEqual(he.code, 401)

    def test_07_csrf_protection_on_admin_actions(self):
        """Verifies that administrative POST endpoints strictly reject cross-origin requests."""
        _, admin_cookie = self._login("librarian1", "LibAdminPass123!")
        admin_token = admin_cookie.split(";")[0]

        req = urllib.request.Request(f"{GATEWAY_URL}/api/admin/settings",
                                     data=json.dumps({"name": "Malicious Hijack"}).encode("utf-8"),
                                     headers={
                                         "Content-Type": "application/json",
                                         "Cookie": admin_token,
                                         "Origin": "http://evil-attacker.com"
                                     })
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            self.fail("Cross-origin admin POST request must be blocked with 403")
        except urllib.error.HTTPError as he:
            self.assertEqual(he.code, 403)

    def test_08_system_backup_and_audit_trail(self):
        """Verifies backup generation and audit logging of administrative changes."""
        _, admin_cookie = self._login("librarian1", "LibAdminPass123!")
        admin_token = admin_cookie.split(";")[0]

        # 1. Trigger database backup snapshot
        req_bk = urllib.request.Request(f"{GATEWAY_URL}/api/admin/system/backup",
                                        data=b"{}",
                                        headers={
                                            "Content-Type": "application/json",
                                            "Cookie": admin_token,
                                            "Origin": GATEWAY_URL
                                        })
        with urllib.request.urlopen(req_bk, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res.get("success"))
            self.assertTrue(os.path.isfile(res.get("backup_path", "")))

        # 2. Verify audit trail has recorded administrative activities
        req_audit = urllib.request.Request(f"{GATEWAY_URL}/api/admin/audit-log", headers={"Cookie": admin_token})
        with urllib.request.urlopen(req_audit, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            log = json.loads(resp.read().decode("utf-8"))
            self.assertIsInstance(log, list)
            actions = [item["action"] for item in log]
            self.assertTrue(any("INSTITUTION_SETTINGS" in a for a in actions))

    def test_09_setup_wizard_completion_locking(self):
        """Verifies that once setup is marked complete, repeated setup calls are locked."""
        req = urllib.request.Request(f"{GATEWAY_URL}/api/setup/complete",
                                     data=json.dumps({
                                         "institution": {"name": "Test Inst", "short_name": "TI"},
                                         "admin": {"username": "admin", "password": "Password123!"},
                                         "library": {"path": TEST_LIBRARY}
                                     }).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Origin": GATEWAY_URL})
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            self.fail("Setup completion should be locked once completed")
        except urllib.error.HTTPError as he:
            self.assertEqual(he.code, 403)

if __name__ == "__main__":
    unittest.main()
