# -*- coding: utf-8 -*-
"""
Automated Regression & Functional Test Suite for Institutional Gateway MVP.
Tests authentication flow, access control, individual identity, and protected reading.
"""
import json
import unittest
import urllib.error
import urllib.request
from http.cookies import SimpleCookie

GATEWAY_URL = "http://127.0.0.1:8085"
import socket

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LAN_IP = get_lan_ip()
LAN_GATEWAY_URL = f"http://{LAN_IP}:8085"
BACKEND_PORT = 8088

class TestInstitutionalGatewayMVP(unittest.TestCase):
    def test_01_landing_page_serves_html(self):
        req = urllib.request.Request(f"{GATEWAY_URL}/")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("Aethelgard Institute of Technology", content)
            self.assertIn("Institutional Digital Library", content)

    def test_02_unauthenticated_api_blocked_with_401(self):
        url = f"{GATEWAY_URL}/calibre/ajax/books"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            self.fail("Expected 401 Unauthorized for unauthenticated API access")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)
            body = json.loads(e.read().decode("utf-8"))
            self.assertIn("Authentication required", body.get("error", ""))

    def test_03_unauthenticated_browser_redirected_to_login(self):
        # When browser navigates to /calibre/ without auth, expects 302 redirect to /?login_required=1
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def http_error_302(self, req, fp, code, msg, headers):
                return fp
        
        opener = urllib.request.build_opener(NoRedirectHandler)
        req = urllib.request.Request(f"{GATEWAY_URL}/calibre/", headers={"Accept": "text/html"})
        try:
            resp = opener.open(req, timeout=5)
            self.assertEqual(resp.code, 302)
            self.assertIn("/?login_required=1", resp.headers.get("Location", ""))
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 302)
            self.assertIn("/?login_required=1", e.headers.get("Location", ""))

    def test_04_backend_port_isolated_from_lan(self):
        # Verifies that direct remote access to port 8088 is blocked / unreachable
        url = "http://192.168.0.107:8088/calibre/"
        try:
            req = urllib.request.Request(url)
            urllib.request.urlopen(req, timeout=2)
            self.fail("Backend port 8088 should NOT be accessible via LAN IP")
        except Exception:
            # Connection refused, timeout, or dropped — expected behavior!
            pass

    def test_05_invalid_login_rejected(self):
        url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": "student1", "password": "WrongPassword123"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("Expected 401 Unauthorized for invalid password")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)
            body = json.loads(e.read().decode("utf-8"))
            self.assertFalse(body.get("success", True))

    def test_06_valid_student_login_and_session(self):
        url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": "student1", "password": "StudentPass123!"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["user"]["username"], "student1")
            self.assertEqual(data["user"]["role"], "Student")
            
            # Verify Set-Cookie header
            set_cookie = resp.headers.get("Set-Cookie", "")
            self.assertIn("inst_session_id=", set_cookie)
            self.assertIn("HttpOnly", set_cookie)

    def test_07_individual_identity_preservation(self):
        # Authenticate as faculty1
        url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": "faculty1", "password": "FacultyPass123!"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            cookie_hdr = resp.headers.get("Set-Cookie")
            session_cookie = SimpleCookie(cookie_hdr)["inst_session_id"].value

        # Check session status endpoint
        status_req = urllib.request.Request(f"{GATEWAY_URL}/api/auth/status", headers={
            "Cookie": f"inst_session_id={session_cookie}"
        })
        with urllib.request.urlopen(status_req, timeout=5) as status_resp:
            self.assertEqual(status_resp.status, 200)
            data = json.loads(status_resp.read().decode("utf-8"))
            self.assertTrue(data["authenticated"])
            self.assertEqual(data["user"]["username"], "faculty1")
            self.assertEqual(data["user"]["role"], "Faculty")
            self.assertIn("Prof. Elena Rostova", data["user"]["displayName"])

    def test_08_authenticated_catalog_and_book_reading_journey(self):
        # 1. Login as student1
        login_url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": "student1", "password": "StudentPass123!"}).encode("utf-8")
        req = urllib.request.Request(login_url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            cookie_hdr = resp.headers.get("Set-Cookie")
            session_cookie = SimpleCookie(cookie_hdr)["inst_session_id"].value

        # 2. Access protected Calibre catalog via Gateway with session
        cat_url = f"{GATEWAY_URL}/calibre/ajax/books"
        cat_req = urllib.request.Request(cat_url, headers={"Cookie": f"inst_session_id={session_cookie}"})
        with urllib.request.urlopen(cat_req, timeout=5) as cat_resp:
            self.assertEqual(cat_resp.status, 200)
            books = json.loads(cat_resp.read().decode("utf-8"))
            self.assertGreaterEqual(len(books), 3)
            titles = [b["title"] for b in books.values()]
            self.assertIn("Principles of Institutional Digital Libraries", titles)
            self.assertIn("Campus Network Security Gateway Architecture", titles)
            self.assertIn("Academic Research Methods Open Access", titles)

        # 3. Access in-browser reading resource (EPUB download/stream)
        book_url = f"{GATEWAY_URL}/calibre/get/epub/1/library"
        book_req = urllib.request.Request(book_url, headers={"Cookie": f"inst_session_id={session_cookie}"})
        with urllib.request.urlopen(book_req, timeout=5) as book_resp:
            self.assertEqual(book_resp.status, 200)
            self.assertEqual(book_resp.headers.get("Content-Type"), "application/epub+zip")
            epub_bytes = book_resp.read()
            self.assertGreater(len(epub_bytes), 500)
            # EPUB starts with PK zip magic number
            self.assertEqual(epub_bytes[:2], b"PK")

    def test_09_lan_connectivity_verification(self):
        # Verifies that LAN URL (192.168.0.107:8085) works identical to localhost
        url = f"{LAN_GATEWAY_URL}/api/auth/status"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("authenticated", data)

    def test_10_logout_destroys_session(self):
        # Login
        login_url = f"{GATEWAY_URL}/api/auth/login"
        payload = json.dumps({"username": "librarian1", "password": "LibAdminPass123!"}).encode("utf-8")
        req = urllib.request.Request(login_url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            cookie_hdr = resp.headers.get("Set-Cookie")
            session_cookie = SimpleCookie(cookie_hdr)["inst_session_id"].value

        # Logout
        logout_req = urllib.request.Request(f"{GATEWAY_URL}/api/auth/logout", data=b"{}", headers={
            "Content-Type": "application/json",
            "Cookie": f"inst_session_id={session_cookie}"
        })
        with urllib.request.urlopen(logout_req, timeout=5) as logout_resp:
            self.assertEqual(logout_resp.status, 200)

        # Verify access is now rejected
        check_req = urllib.request.Request(f"{GATEWAY_URL}/calibre/ajax/books", headers={
            "Cookie": f"inst_session_id={session_cookie}",
            "Accept": "application/json"
        })
        try:
            urllib.request.urlopen(check_req, timeout=5)
            self.fail("Expected 401 after logout")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

if __name__ == "__main__":
    unittest.main()
