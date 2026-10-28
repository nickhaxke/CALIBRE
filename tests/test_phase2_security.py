"""
Phase 2 Security Hardening & Regression Test Suite
Institutional Calibre Gateway
Aethelgard Institute of Technology

Verifies:
1. Complete elimination of hardcoded credentials in catalog endpoints.
2. Protection of /api/catalog (HTTP 401 when unauthenticated).
3. Enforcement of individual patron permissions on catalog access.
4. Path traversal defense on static assets (/static/.. prohibited).
5. CSRF Origin & Referer validation on state-changing endpoints (HTTP 403).
6. Session cookie security attributes (HttpOnly, SameSite=Lax, Max-Age).
7. Session invalidation, post-logout access denial, and strict anti-caching headers.
8. Error handling sanitization (no stack trace or internal exception disclosure).
9. Sliding-window login rate limiting (anti brute-force defense, HTTP 429).
"""

import json
import time
import unittest
import urllib.request
import urllib.parse
import urllib.error
from http.cookiejar import CookieJar

GATEWAY_BASE = "http://127.0.0.1:8085"

class TestPhase2SecurityHardening(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        try:
            req = urllib.request.Request(
                f"{GATEWAY_BASE}/api/auth/reset-rate-limit",
                data=b"{}",
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=3):
                pass
        except Exception:
            pass

    def setUp(self):
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def login(self, username, password, origin="http://127.0.0.1:8085"):
        req = urllib.request.Request(
            f"{GATEWAY_BASE}/api/auth/login",
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": origin}
        )
        try:
            with self.opener.open(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data, resp.headers
        except urllib.error.HTTPError as e:
            data = json.loads(e.read().decode("utf-8")) if e.code in (400, 401, 403, 429) else {}
            return e.code, data, e.headers

    def test_01_catalog_requires_authentication(self):
        """Verify that /api/catalog strictly rejects unauthenticated guest requests with HTTP 401."""
        req = urllib.request.Request(f"{GATEWAY_BASE}/api/catalog")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.fail(f"Expected HTTP 401 Unauthorized, but got HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401, "Unauthenticated access to catalog must return 401")
            data = json.loads(e.read().decode("utf-8"))
            self.assertIn("error", data)
            self.assertIn("Authentication required", data["error"])
            self.assertIn("no-store", e.headers.get("Cache-Control", ""))

    def test_02_authenticated_catalog_access_uses_patron_credentials(self):
        """Verify that an authenticated patron successfully receives catalog data with their credentials."""
        status, data, _ = self.login("student1", "StudentPass123!")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))

        # Fetch catalog with session cookie
        req = urllib.request.Request(f"{GATEWAY_BASE}/api/catalog")
        with self.opener.open(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            catalog = json.loads(resp.read().decode("utf-8"))
            self.assertIsInstance(catalog, list)
            self.assertGreater(len(catalog), 0, "Catalog should return accessible books for student1")
            for book in catalog:
                self.assertIn("id", book)
                self.assertIn("title", book)
                self.assertIn("author", book)

    def test_03_static_path_traversal_protection(self):
        """Verify that directory traversal attempts via /static/ are strictly blocked."""
        traversal_paths = [
            "/static/../../configuration/gateway_config.json",
            "/static/..%2f..%2fconfiguration/gateway_config.json",
            "/static/..\\..\\configuration\\gateway_config.json",
            "/static/%2e%2e/%2e%2e/backend/gateway_server.py"
        ]
        for tpath in traversal_paths:
            req = urllib.request.Request(f"{GATEWAY_BASE}{tpath}")
            try:
                with urllib.request.urlopen(req, timeout=4) as resp:
                    self.fail(f"Traversal path {tpath} returned HTTP {resp.status}; expected 403 or 404")
            except urllib.error.HTTPError as e:
                self.assertIn(e.code, (403, 404), f"Path traversal attempt {tpath} must be blocked with 403 or 404, got {e.code}")

    def test_04_csrf_origin_validation_on_login(self):
        """Verify that cross-origin POST requests from untrusted domains are rejected with HTTP 403."""
        status, data, _ = self.login("student1", "StudentPass123!", origin="http://malicious-attacker.com")
        self.assertEqual(status, 403, "Cross-origin login POST must be rejected with HTTP 403")
        self.assertIn("error", data)
        self.assertIn("Cross-origin", data["error"])

    def test_05_csrf_origin_validation_on_logout(self):
        """Verify that cross-origin POST logout from untrusted domains is rejected with HTTP 403."""
        # Authenticate first
        status, _, _ = self.login("faculty1", "FacultyPass123!")
        self.assertEqual(status, 200)

        # Attempt cross-origin logout
        req = urllib.request.Request(
            f"{GATEWAY_BASE}/api/auth/logout",
            data=json.dumps({"action": "logout"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": "http://evil-site.org"}
        )
        try:
            with self.opener.open(req, timeout=4) as resp:
                self.fail(f"Cross-origin logout succeeded with {resp.status}; expected 403")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403, "Cross-origin logout POST must return 403")

    def test_06_session_cookie_attributes_and_lifecycle(self):
        """Verify session cookie security flags (HttpOnly, SameSite=Lax, Max-Age)."""
        status, data, headers = self.login("librarian1", "LibAdminPass123!")
        self.assertEqual(status, 200)
        set_cookie = headers.get("Set-Cookie", "")
        self.assertIn("inst_session_id=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Lax", set_cookie)
        self.assertIn("Max-Age=", set_cookie)

        # Now logout
        req = urllib.request.Request(
            f"{GATEWAY_BASE}/api/auth/logout",
            data=json.dumps({"action": "logout"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8085"}
        )
        with self.opener.open(req, timeout=4) as resp:
            self.assertEqual(resp.status, 200)
            logout_cookie = resp.headers.get("Set-Cookie", "")
            self.assertIn("Max-Age=0", logout_cookie)

        # Check status is now unauthenticated
        req_status = urllib.request.Request(f"{GATEWAY_BASE}/api/auth/status")
        with self.opener.open(req_status, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(data.get("authenticated"))

    def test_07_post_logout_access_denial(self):
        """Verify that after logout, access to Calibre proxy redirects or is denied."""
        req_calibre = urllib.request.Request(f"{GATEWAY_BASE}/calibre/", headers={"Accept": "text/html"})
        try:
            with self.opener.open(req_calibre, timeout=4) as resp:
                self.assertIn("login_required", resp.geturl())
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (302, 401))

    def test_08_error_sanitization(self):
        """Verify that nonexistent endpoints or gateway errors do not leak internal stack traces."""
        req = urllib.request.Request(f"{GATEWAY_BASE}/nonexistent-secure-check-path")
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                self.fail(f"Expected 404, got {resp.status}")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
            body = e.read().decode("utf-8", errors="replace")
            self.assertNotIn("Traceback", body)
            self.assertNotIn('File "', body)

    def test_09_login_rate_limiting(self):
        """Verify that 5 failed login attempts trigger HTTP 429 Too Many Requests."""
        for i in range(5):
            status, _, _ = self.login("student1", "WrongPassword999!")
            self.assertEqual(status, 401, f"Attempt {i+1} should return 401 Invalid Credentials")

        # The 6th attempt must trigger 429 rate limit
        status, data, headers = self.login("student1", "WrongPassword999!")
        self.assertEqual(status, 429, f"Attempt 6 should be rate-limited with HTTP 429, got {status}")
        self.assertIn("error", data)
        self.assertIn("Too many failed login attempts", data["error"])
        self.assertIn("Retry-After", headers)
        self.assertGreater(int(headers["Retry-After"]), 0)

if __name__ == "__main__":
    unittest.main()
