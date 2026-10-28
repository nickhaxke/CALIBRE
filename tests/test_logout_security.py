# -*- coding: utf-8 -*-
"""
Security and Regression Test Suite: Institutional Calibre Gateway Logout
Verifies:
1. Injected institutional header and Sign Out button in /calibre/ HTML
2. Calibre native dialog MutationObserver enhancement
3. Strict anti-caching headers on all protected endpoints
4. POST and GET /api/auth/logout session invalidation and cookie expiration
5. Rejection of unauthenticated and post-logout access to /calibre/ and protected book downloads
6. Seamless switching between users (student1 -> faculty1) without browser restart
7. Multi-user session isolation (logging out patron A does not affect patron B)
8. Absence of backend credentials or Basic Auth tokens in frontend responses
"""
import base64
import json
import unittest
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie

GATEWAY_URL = "http://127.0.0.1:8085"

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        return fp

class CalibreGatewayLogoutSecurityTests(unittest.TestCase):

    def setUp(self):
        self.opener = urllib.request.build_opener(NoRedirectHandler)

    def test_01_landing_page_anti_cache(self):
        req = urllib.request.Request(f"{GATEWAY_URL}/")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            cache_ctrl = resp.headers.get("Cache-Control", "")
            self.assertIn("no-store", cache_ctrl)
            self.assertIn("no-cache", cache_ctrl)

    def test_02_unauthenticated_calibre_redirect(self):
        req = urllib.request.Request(f"{GATEWAY_URL}/calibre/", headers={"Accept": "text/html"})
        resp = self.opener.open(req, timeout=5)
        self.assertEqual(resp.code, 302)
        loc = resp.headers.get("Location", "")
        self.assertIn("/?login_required=1", loc)
        cache_ctrl = resp.headers.get("Cache-Control", "")
        self.assertIn("no-store", cache_ctrl)

    def test_03_unauthenticated_api_and_book_rejection(self):
        # 1. API endpoint
        req = urllib.request.Request(f"{GATEWAY_URL}/calibre/ajax/books", headers={"Accept": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("Expected 401 Unauthorized for unauthenticated API")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)
            body = json.loads(e.read().decode("utf-8"))
            self.assertIn("Authentication required", body.get("error", ""))

        # 2. Protected EPUB volume
        req_book = urllib.request.Request(f"{GATEWAY_URL}/calibre/get/epub/1/library")
        try:
            urllib.request.urlopen(req_book, timeout=5)
            self.fail("Expected 401 Unauthorized for unauthenticated EPUB download")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

    def test_04_student_login_and_ui_injection(self):
        # Authenticate as student1
        login_url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": "student1", "password": "StudentPass123!"}).encode("utf-8")
        req = urllib.request.Request(login_url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            cookie_hdr = resp.headers.get("Set-Cookie")
            self.assertIn("inst_session_id=", cookie_hdr)
            session_cookie = SimpleCookie(cookie_hdr)["inst_session_id"].value

        # Fetch /calibre/ with session cookie
        calibre_req = urllib.request.Request(f"{GATEWAY_URL}/calibre/", headers={
            "Cookie": f"inst_session_id={session_cookie}",
            "Accept": "text/html"
        })
        with urllib.request.urlopen(calibre_req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            cache_ctrl = resp.headers.get("Cache-Control", "")
            self.assertIn("no-store", cache_ctrl)
            self.assertIn("must-revalidate", cache_ctrl)

            html_content = resp.read().decode("utf-8", errors="replace")
            
            # Verify injected institutional top bar
            self.assertIn('id="inst-calibre-nav"', html_content)
            self.assertIn("Aethelgard Institute of Technology", html_content)
            self.assertIn("Alex Rivera (Student ID: #8841)", html_content)
            self.assertIn("(Student)", html_content)
            self.assertIn('id="inst-nav-signout-btn"', html_content)
            self.assertIn("performInstitutionalSignOut()", html_content)

            # Verify MutationObserver for Calibre's native user dialog
            self.assertIn("inst-calibre-bridge", html_content)
            self.assertIn("To log in as a different user", html_content)
            self.assertIn("Sign Out of Institutional Library", html_content)

            # Verify layout compensation
            self.assertIn("margin-top: 44px", html_content)

    def test_05_ajax_logout_invalidates_session_and_expires_cookie(self):
        # 1. Login
        login_url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": "student1", "password": "StudentPass123!"}).encode("utf-8")
        req = urllib.request.Request(login_url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            cookie_hdr = resp.headers.get("Set-Cookie")
            session_cookie = SimpleCookie(cookie_hdr)["inst_session_id"].value

        # 2. Confirm valid access before logout
        cat_req = urllib.request.Request(f"{GATEWAY_URL}/calibre/ajax/books", headers={"Cookie": f"inst_session_id={session_cookie}"})
        with urllib.request.urlopen(cat_req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

        # 3. Post Logout
        logout_req = urllib.request.Request(f"{GATEWAY_URL}/api/auth/logout", data=b"{}", headers={
            "Content-Type": "application/json",
            "Cookie": f"inst_session_id={session_cookie}"
        })
        with urllib.request.urlopen(logout_req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("success"))
            self.assertIn("?logged_out=1", data.get("redirect", ""))
            
            # Check cookie expiration
            set_cookie = resp.headers.get("Set-Cookie", "")
            self.assertIn("Max-Age=0", set_cookie)
            self.assertIn("1970", set_cookie)

        # 4. Status API must now return unauthenticated
        status_req = urllib.request.Request(f"{GATEWAY_URL}/api/auth/status", headers={"Cookie": f"inst_session_id={session_cookie}"})
        with urllib.request.urlopen(status_req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(data["authenticated"])

        # 5. Subsequent access to /calibre/ must be redirected
        check_calibre = urllib.request.Request(f"{GATEWAY_URL}/calibre/", headers={
            "Cookie": f"inst_session_id={session_cookie}",
            "Accept": "text/html"
        })
        resp = self.opener.open(check_calibre, timeout=5)
        self.assertEqual(resp.code, 302)
        self.assertIn("/?login_required=1", resp.headers.get("Location", ""))

        # 6. Subsequent access to book stream must be 401
        book_req = urllib.request.Request(f"{GATEWAY_URL}/calibre/get/epub/1/library", headers={"Cookie": f"inst_session_id={session_cookie}"})
        try:
            urllib.request.urlopen(book_req, timeout=5)
            self.fail("Expected 401 for EPUB access with destroyed session")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

    def test_06_direct_get_logout_redirect(self):
        # Authenticate as faculty1
        login_url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": "faculty1", "password": "FacultyPass123!"}).encode("utf-8")
        req = urllib.request.Request(login_url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            cookie_hdr = resp.headers.get("Set-Cookie")
            session_cookie = SimpleCookie(cookie_hdr)["inst_session_id"].value

        # Issue GET /api/auth/logout
        get_logout = urllib.request.Request(f"{GATEWAY_URL}/api/auth/logout", headers={"Cookie": f"inst_session_id={session_cookie}"})
        resp = self.opener.open(get_logout, timeout=5)
        self.assertEqual(resp.code, 302)
        self.assertIn("/?logged_out=1", resp.headers.get("Location", ""))
        self.assertIn("Max-Age=0", resp.headers.get("Set-Cookie", ""))

        # Verify session is destroyed
        status_req = urllib.request.Request(f"{GATEWAY_URL}/api/auth/status", headers={"Cookie": f"inst_session_id={session_cookie}"})
        with urllib.request.urlopen(status_req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(data["authenticated"])

    def test_07_immediate_user_switch_without_browser_restart(self):
        # 1. Login as student1
        login_url = f"{GATEWAY_URL}/api/auth/login"
        p1 = json.dumps({"username": "student1", "password": "StudentPass123!"}).encode("utf-8")
        req1 = urllib.request.Request(login_url, data=p1, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req1, timeout=5) as resp1:
            cookie1 = SimpleCookie(resp1.headers.get("Set-Cookie"))["inst_session_id"].value

        # Verify student1 identity in UI
        c_req1 = urllib.request.Request(f"{GATEWAY_URL}/calibre/", headers={"Cookie": f"inst_session_id={cookie1}", "Accept": "text/html"})
        with urllib.request.urlopen(c_req1, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            self.assertIn("Alex Rivera", body)
            self.assertIn("(Student)", body)

        # 2. Sign out student1
        out_req = urllib.request.Request(f"{GATEWAY_URL}/api/auth/logout", data=b"{}", headers={
            "Content-Type": "application/json",
            "Cookie": f"inst_session_id={cookie1}"
        })
        with urllib.request.urlopen(out_req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

        # 3. Immediately sign in as faculty1 (SAME CLIENT PROCESS, NO RESTART)
        p2 = json.dumps({"username": "faculty1", "password": "FacultyPass123!"}).encode("utf-8")
        req2 = urllib.request.Request(login_url, data=p2, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req2, timeout=5) as resp2:
            self.assertEqual(resp2.status, 200)
            cookie2 = SimpleCookie(resp2.headers.get("Set-Cookie"))["inst_session_id"].value

        # Verify faculty1 identity in UI
        c_req2 = urllib.request.Request(f"{GATEWAY_URL}/calibre/", headers={"Cookie": f"inst_session_id={cookie2}", "Accept": "text/html"})
        with urllib.request.urlopen(c_req2, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            self.assertIn("Prof. Elena Rostova", body)
            self.assertIn("(Faculty)", body)
            self.assertNotIn("Alex Rivera", body)

    def test_08_multiple_concurrent_sessions_isolation(self):
        # Create Session A (student1)
        login_url = f"{GATEWAY_URL}/api/auth/login"
        pa = json.dumps({"username": "student1", "password": "StudentPass123!"}).encode("utf-8")
        with urllib.request.urlopen(urllib.request.Request(login_url, data=pa, headers={"Content-Type": "application/json"})) as ra:
            cookie_a = SimpleCookie(ra.headers.get("Set-Cookie"))["inst_session_id"].value

        # Create Session B (librarian1)
        pb = json.dumps({"username": "librarian1", "password": "LibAdminPass123!"}).encode("utf-8")
        with urllib.request.urlopen(urllib.request.Request(login_url, data=pb, headers={"Content-Type": "application/json"})) as rb:
            cookie_b = SimpleCookie(rb.headers.get("Set-Cookie"))["inst_session_id"].value

        # Both sessions active
        self.assertNotEqual(cookie_a, cookie_b)

        # Log out Session A
        out_a = urllib.request.Request(f"{GATEWAY_URL}/api/auth/logout", data=b"{}", headers={
            "Content-Type": "application/json",
            "Cookie": f"inst_session_id={cookie_a}"
        })
        with urllib.request.urlopen(out_a, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

        # Session A is dead
        status_a = urllib.request.Request(f"{GATEWAY_URL}/api/auth/status", headers={"Cookie": f"inst_session_id={cookie_a}"})
        with urllib.request.urlopen(status_a, timeout=5) as resp:
            self.assertFalse(json.loads(resp.read().decode("utf-8"))["authenticated"])

        # Session B is STILL ALIVE and HEALTHY!
        status_b = urllib.request.Request(f"{GATEWAY_URL}/api/auth/status", headers={"Cookie": f"inst_session_id={cookie_b}"})
        with urllib.request.urlopen(status_b, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["authenticated"])
            self.assertEqual(data["user"]["username"], "librarian1")

    def test_09_no_credentials_leakage(self):
        # Login as student1
        login_url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": "student1", "password": "StudentPass123!"}).encode("utf-8")
        with urllib.request.urlopen(urllib.request.Request(login_url, data=payload, headers={"Content-Type": "application/json"})) as resp:
            login_body = resp.read().decode("utf-8")
            cookie_val = SimpleCookie(resp.headers.get("Set-Cookie"))["inst_session_id"].value

        # Check login response body
        self.assertNotIn("StudentPass123!", login_body)
        self.assertNotIn("basic_auth", login_body)

        # Check status endpoint
        status_req = urllib.request.Request(f"{GATEWAY_URL}/api/auth/status", headers={"Cookie": f"inst_session_id={cookie_val}"})
        with urllib.request.urlopen(status_req) as resp:
            status_body = resp.read().decode("utf-8")
            self.assertNotIn("StudentPass123!", status_body)
            self.assertNotIn("basic_auth", status_body)

        # Check proxied HTML
        calibre_req = urllib.request.Request(f"{GATEWAY_URL}/calibre/", headers={"Cookie": f"inst_session_id={cookie_val}", "Accept": "text/html"})
        with urllib.request.urlopen(calibre_req) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            self.assertNotIn("StudentPass123!", html)
            b64_hash = base64.b64encode(b"student1:StudentPass123!").decode("ascii")
            self.assertNotIn(b64_hash, html)

if __name__ == "__main__":
    unittest.main()
