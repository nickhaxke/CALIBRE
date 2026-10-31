"""
Comprehensive Automated Test Suite for Client Feedback Implementation (Loops 2–9):
- Loop 2: Public Catalogue Cleanup (no hero marketing copy, no public collection counts, no facet count badges)
- Loop 3: Complete Search Functionality (explicit Search button, Enter submit, field-specific search, combined filters)
- Loop 4: Professional Book Details (no 'Pages: 0', 'Read Online' primary action, no 'Open in classic Calibre' for students)
- Loop 5: Branded Institutional PDF Reader (info, single-page PNG rendering, full-text search, HTTP Range 206, corrupt/missing/unauthorized handling, download policy enforcement)
- Loop 6: Critical Student Permissions Audit (blocks convert, edit, delete, upload, notes, FTS for students; preserves Admin capabilities)
"""

import importlib.util
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

ROOT = Path(__file__).resolve().parents[1]
TEST_ENV_DIR = tempfile.TemporaryDirectory(prefix="inst-client-feedback-")
os.environ["CALIBRE_INSTITUTIONAL_CONFIG_DIR"] = TEST_ENV_DIR.name
os.environ["CALIBRE_INSTITUTIONAL_GATEWAY_CONFIG"] = str(ROOT / "customization" / "configuration" / "gateway_config.json")

sys.path.insert(0, str(ROOT / "customization" / "backend"))
sys.path.insert(0, str(ROOT / "upstream" / "calibre" / "src"))

import gateway_server as gateway
from config_manager import ConfigManager


VALID_TEST_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 68 >> stream
BT /F1 18 Tf 72 700 Td (TANRAIL Operations Manual Page One) Tj ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
6 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 7 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
7 0 obj << /Length 70 >> stream
BT /F1 18 Tf 72 700 Td (Locomotive Safety Protocol Page Two) Tj ET
endstream endobj
xref
0 8
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000121 00000 n 
0000000235 00000 n 
0000000352 00000 n 
0000000420 00000 n 
0000000534 00000 n 
trailer << /Size 8 /Root 1 0 R >>
startxref
653
%%EOF
"""


def create_test_calibre_library(lib_dir: Path):
    """Creates a realistic Calibre metadata.db and book files (PDF, EPUB, Corrupt PDF, Formatless) for testing."""
    lib_dir.mkdir(parents=True, exist_ok=True)
    db_path = lib_dir / "metadata.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            title TEXT,
            sort TEXT,
            timestamp TEXT,
            pubdate TEXT,
            series_index REAL DEFAULT 1.0,
            author_sort TEXT,
            isbn TEXT DEFAULT '',
            lccn TEXT DEFAULT '',
            path TEXT DEFAULT '',
            flags INTEGER DEFAULT 1,
            uuid TEXT DEFAULT '',
            has_cover BOOL DEFAULT 0,
            last_modified TEXT DEFAULT '2026-10-30T00:00:00+00:00'
        );
        CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT, sort TEXT, link TEXT DEFAULT '');
        CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER, author INTEGER);
        CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
        CREATE TABLE books_publishers_link (id INTEGER PRIMARY KEY, book INTEGER, publisher INTEGER);
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY, book INTEGER, tag INTEGER);
        CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
        CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, uncompressed_size INTEGER, name TEXT);
    """)

    # Book 1: Valid 2-page PDF
    b1_dir = lib_dir / "TANRAIL" / "Operations Manual (1)"
    b1_dir.mkdir(parents=True, exist_ok=True)
    pdf1_file = b1_dir / "Operations Manual - TANRAIL.pdf"
    pdf1_file.write_bytes(VALID_TEST_PDF)

    cur.execute(
        "INSERT INTO books (id, title, author_sort, pubdate, path) VALUES (1, 'TANRAIL Operations Manual', 'TANRAIL Engineering', '2026-05-10', 'TANRAIL/Operations Manual (1)')"
    )
    cur.execute("INSERT INTO authors (id, name, sort) VALUES (1, 'TANRAIL Engineering', 'TANRAIL Engineering')")
    cur.execute("INSERT INTO books_authors_link (book, author) VALUES (1, 1)")
    cur.execute("INSERT INTO publishers (id, name, sort) VALUES (1, 'TANRAIL Press', 'TANRAIL Press')")
    cur.execute("INSERT INTO books_publishers_link (book, publisher) VALUES (1, 1)")
    cur.execute("INSERT INTO tags (id, name) VALUES (1, 'Railways')")
    cur.execute("INSERT INTO books_tags_link (book, tag) VALUES (1, 1)")
    cur.execute(
        "INSERT INTO data (book, format, uncompressed_size, name) VALUES (1, 'PDF', ?, 'Operations Manual - TANRAIL')",
        (len(VALID_TEST_PDF),)
    )

    # Book 2: EPUB only (no PDF)
    b2_dir = lib_dir / "Schember" / "Quick Start Guide (2)"
    b2_dir.mkdir(parents=True, exist_ok=True)
    (b2_dir / "Quick Start Guide.epub").write_bytes(b"PK\x03\x04dummy-epub")
    cur.execute(
        "INSERT INTO books (id, title, author_sort, pubdate, path) VALUES (2, 'Quick Start Guide', 'John Schember', '2025-01-15', 'Schember/Quick Start Guide (2)')"
    )
    cur.execute("INSERT INTO authors (id, name, sort) VALUES (2, 'John Schember', 'Schember, John')")
    cur.execute("INSERT INTO books_authors_link (book, author) VALUES (2, 2)")
    cur.execute("INSERT INTO data (book, format, uncompressed_size, name) VALUES (2, 'EPUB', 16, 'Quick Start Guide')")

    # Book 3: Corrupt PDF
    b3_dir = lib_dir / "Corrupt" / "Damaged Book (3)"
    b3_dir.mkdir(parents=True, exist_ok=True)
    (b3_dir / "Damaged Book.pdf").write_bytes(b"NOT_A_VALID_PDF_HEADER_CORRUPT_CONTENT_1234567890")
    cur.execute(
        "INSERT INTO books (id, title, author_sort, pubdate, path) VALUES (3, 'Damaged Book', 'Unknown', '2024-01-01', 'Corrupt/Damaged Book (3)')"
    )
    cur.execute("INSERT INTO data (book, format, uncompressed_size, name) VALUES (3, 'PDF', 49, 'Damaged Book')")

    # Book 4: No formats attached
    b4_dir = lib_dir / "Archive" / "Reference Record (4)"
    b4_dir.mkdir(parents=True, exist_ok=True)
    cur.execute(
        "INSERT INTO books (id, title, author_sort, pubdate, path) VALUES (4, 'Reference Only Record', 'Archive Staff', '0101-01-01', 'Archive/Reference Record (4)')"
    )

    conn.commit()
    conn.close()


class ClientFeedbackV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(TEST_ENV_DIR.name)
        cls.cfg_db = cls.base / "institutional_config.sqlite"
        cls.user_db = cls.base / "server-users.sqlite"
        cls.main_lib = cls.base / "TANRAIL_Main_Library"
        cls.faculty_lib = cls.base / "Faculty_Restricted_Library"

        create_test_calibre_library(cls.main_lib)
        create_test_calibre_library(cls.faculty_lib)

        cls.cm = ConfigManager(db_path=str(cls.cfg_db))
        cls.cm.update_institution_settings(
            institution_name="TANRAIL LIBRARY",
            short_name="TLB",
            library_title="TANRAIL Digital Collections",
            primary_color="#183c34",
            actor="test"
        )

        lib1 = cls.cm.add_library(
            display_name="TANRAIL Digital Collections",
            path=str(cls.main_lib),
            is_default=True,
            is_active=True,
            access_policy="institutional",
            actor="test"
        )
        cls.lib1_id = lib1["library_id"] if isinstance(lib1, dict) else lib1
        lib2 = cls.cm.add_library(
            display_name="Faculty Restricted Collection",
            path=str(cls.faculty_lib),
            is_default=False,
            is_active=True,
            access_policy="faculty_only",
            actor="test"
        )
        cls.lib2_id = lib2["library_id"] if isinstance(lib2, dict) else lib2
        cls.cm.set_config_value("setup_completed", "1")

        cls.cm.set_user_profile("admin", "Administrator", "Chief Admin", "IT", is_active=True, allowed_libraries="*")
        cls.cm.set_user_profile("student", "Student", "nick", "Engineering", is_active=True, allowed_libraries="*")
        cls.cm.set_user_profile("faculty", "Faculty", "Dr. K. Mushi", "Research", is_active=True, allowed_libraries="*")

        gateway.CONFIG_MANAGER = cls.cm

    def make_handler(self, path="/", method="GET", token=None, headers=None, body=b""):
        h = object.__new__(gateway.InstitutionalGatewayHandler)
        h.path = path
        h.command = method
        h.client_address = ("127.0.0.1", 55123)
        hdrs = dict(headers or {})
        if token:
            hdrs["Cookie"] = f"{gateway.COOKIE_NAME}={token}"
        if body and "Content-Length" not in hdrs:
            hdrs["Content-Length"] = str(len(body))
        h.headers = hdrs
        h.rfile = io.BytesIO(body)
        h.wfile = io.BytesIO()
        h.status_code = None
        h.sent_headers = {}
        h.json_response = None

        def send_response(code, message=None):
            h.status_code = code

        def send_header(k, v):
            h.sent_headers[k] = v

        def end_headers():
            pass

        def send_json(code, data, extra_headers=None):
            h.status_code = code
            h.json_response = data
            if extra_headers:
                h.sent_headers.update(extra_headers)

        def send_error(code, message=None):
            h.status_code = code
            h.json_response = {"error": message or "Error"}

        h.send_response = send_response
        h.send_header = send_header
        h.end_headers = end_headers
        h.send_json = send_json
        h.send_error = send_error
        return h

    def test_01_loop2_public_catalogue_cleanup_verified(self):
        """Loop 2: Verify rejected hero copy, collection counts, and Classic Calibre links are removed from catalogue assets."""
        assets_dir = ROOT / "upstream" / "calibre" / "src" / "calibre" / "srv" / "institutional_assets"
        html_text = (assets_dir / "index.html").read_text(encoding="utf-8")
        js_text = (assets_dir / "library.js").read_text(encoding="utf-8")

        # Rejected marketing strings and public counters must not exist
        forbidden_phrases = [
            "A world of ideas",
            "Yours to explore",
            "YOUR LIBRARY, OPEN TO POSSIBILITY",
            "volumes to discover",
            "total-mark",
            "all-count",
            "result-count",
            "Classic Calibre",
            "Open in classic Calibre",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, html_text, f"Forbidden phrase '{phrase}' still present in index.html")
            self.assertNotIn(phrase, js_text, f"Forbidden phrase '{phrase}' still present in library.js")

        # Required replacement structure must exist
        self.assertIn("Library Catalogue", html_text)
        self.assertIn('id="search-form"', html_text)
        self.assertIn('id="search-submit"', html_text)
        self.assertIn("Read Online", js_text)

    def test_02_loop3_and_loop4_catalogue_search_fields_and_book_details(self):
        """Loop 3 & 4: Verify field-specific search, no 'Pages: 0', 'Read Online' PDF routing, and facet count removal."""
        import calibre
        src_calibre_dir = str(ROOT / "upstream" / "calibre" / "src" / "calibre")
        if hasattr(calibre, "__path__") and src_calibre_dir not in calibre.__path__:
            calibre.__path__.insert(0, src_calibre_dir)
        inst_path = ROOT / "upstream" / "calibre" / "src" / "calibre" / "srv" / "institutional.py"
        spec = importlib.util.spec_from_file_location("inst_srv_test", str(inst_path))
        inst_srv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst_srv)

        books_meta = {
            1: {
                "title": "TANRAIL Operations Manual",
                "authors": ["TANRAIL Engineering"],
                "publisher": "TANRAIL Press",
                "pubdate": "2026-05-10",
                "series": "Rail Operations",
                "tags": ["Railways", "Safety"],
                "languages": ["eng"],
                "comments": "<p>Comprehensive operational procedures.</p>",
                "cover": "/calibre/get/cover/1/Main",
                "formats": ["PDF"],
                "pages": 0,  # Invalid placeholder must be suppressed!
            },
            2: {
                "title": "Quick Start Guide",
                "authors": ["John Schember"],
                "publisher": "Calibre Press",
                "pubdate": "2025-01-15",
                "series": "",
                "tags": ["Guide"],
                "languages": ["eng"],
                "comments": "Getting started guide.",
                "cover": "/calibre/get/cover/2/Main",
                "formats": ["EPUB"],
                "pages": 42,
            },
            4: {
                "title": "Reference Only Record",
                "authors": ["Archive Staff"],
                "publisher": "",
                "pubdate": "0101-01-01",
                "series": "",
                "tags": [],
                "languages": [],
                "comments": "",
                "cover": "/calibre/get/cover/4/Main",
                "formats": [],
                "pages": 0,
            }
        }

        class FakeDB:
            server_library_id = "TANRAIL_Main_Library"
            safe_read_lock = tempfile.TemporaryDirectory()

            def field_for(self, name, bid, default=None):
                b = books_meta[bid]
                if name == "title":
                    return b["title"]
                if name == "authors":
                    return tuple(b["authors"])
                if name == "pubdate":
                    return b["pubdate"]
                return default

        class FakeCtx:
            def library_info(self, rd):
                return {"TANRAIL_Main_Library": "TANRAIL Digital Collections"}, "TANRAIL_Main_Library"

            def url_for(self, *args, **kwargs):
                return "/calibre"

            def search(self, rd, db, query):
                if not query:
                    return set(books_meta.keys())
                # Verify field-scoped query construction
                if 'title:"Quick"' in query and 'title:"Guide"' in query:
                    return {2}
                if 'title:"Schember"' in query:
                    return set()
                if 'authors:"Schember"' in query:
                    return {2}
                if 'publisher:"TANRAIL"' in query:
                    return {1}
                if 'tags:"Railways"' in query:
                    return {1}
                return set()

            def get_categories(self, rd, db):
                return {
                    "tags": [types.SimpleNamespace(original_name="Railways", count=5)],
                    "authors": [types.SimpleNamespace(original_name="John Schember", count=1)],
                }

        fake_db = FakeDB()
        fake_ctx = FakeCtx()

        with patch.object(inst_srv, "get_db", return_value=fake_db), \
             patch.object(inst_srv, "book_to_json", side_effect=lambda ctx, rd, db, bid, **kw: (books_meta[bid], None)):

            # 1. Default listing: verify PDF reader_url, Pages: 0 suppression, formatless book handling, and facet count removal
            rd_all = types.SimpleNamespace(query={}, username="student", outheaders={})
            res_all = inst_srv.institutional_catalog(fake_ctx, rd_all)
            self.assertEqual(res_all["total"], 3)
            by_id = {b["id"]: b for b in res_all["books"]}

            # Book 1 (PDF): routes to /reader, pages=0 is suppressed
            self.assertEqual(by_id[1]["reader_type"], "pdf")
            self.assertEqual(by_id[1]["reader_url"], "/reader?book_id=1&library_id=TANRAIL_Main_Library")
            self.assertNotIn("pages", by_id[1], "Invalid Pages: 0 placeholder must not be emitted!")
            self.assertFalse(by_id[1]["allow_native"])

            # Book 2 (EPUB): valid pages=42 is preserved
            self.assertEqual(by_id[2]["reader_type"], "ebook")
            self.assertEqual(by_id[2]["pages"], 42)

            # Book 4 (No format): reader_type == 'none', reader_url == '', year '0101' suppressed
            self.assertEqual(by_id[4]["reader_type"], "none")
            self.assertEqual(by_id[4]["reader_url"], "")
            self.assertEqual(by_id[4]["year"], "")

            # Categories must not expose numerical count badges
            self.assertNotIn("count", res_all["categories"]["tags"][0])

            # 2. Field-specific search: Title search for "Quick Guide" matches Book 2
            rd_title = types.SimpleNamespace(query={"q": "Quick Guide", "field": "title"}, username="student", outheaders={})
            res_title = inst_srv.institutional_catalog(fake_ctx, rd_title)
            self.assertEqual([b["id"] for b in res_title["books"]], [2])

            # 3. Field-specific search: Title search for author "Schember" returns 0 results
            rd_title_miss = types.SimpleNamespace(query={"q": "Schember", "field": "title"}, username="student", outheaders={})
            res_title_miss = inst_srv.institutional_catalog(fake_ctx, rd_title_miss)
            self.assertEqual(res_title_miss["total"], 0)

            # 4. Field-specific search: Author search for "Schember" returns Book 2
            rd_author = types.SimpleNamespace(query={"q": "Schember", "field": "authors"}, username="student", outheaders={})
            res_author = inst_srv.institutional_catalog(fake_ctx, rd_author)
            self.assertEqual([b["id"] for b in res_author["books"]], [2])

    def test_03_loop5_branded_pdf_reader_end_to_end(self):
        """Loop 5: Verify PDF reader page, info, PNG rendering, text search, HTTP Range 206, corrupt/missing/unauthorized handling, and download policy."""
        student_token = gateway.create_session("student", "12345678")
        faculty_token = gateway.create_session("faculty", "facpass")
        admin_token = gateway.create_session("admin", "adminpass")

        # 1. Unauthenticated access to /reader redirects to login, and /api/reader/info returns 401
        h_unauth_page = self.make_handler("/reader?book_id=1", "GET")
        h_unauth_page.do_GET()
        self.assertEqual(h_unauth_page.status_code, 302)
        self.assertIn("login_required=1", h_unauth_page.sent_headers.get("Location", ""))

        h_unauth_api = self.make_handler("/api/reader/info?book_id=1", "GET")
        h_unauth_api.do_GET()
        self.assertEqual(h_unauth_api.status_code, 401)

        # 2. Student opens Branded PDF Reader HTML (/reader?book_id=1)
        h_reader_html = self.make_handler(f"/reader?book_id=1&library_id={self.lib1_id}", "GET", token=student_token)
        h_reader_html.do_GET()
        self.assertEqual(h_reader_html.status_code, 200)
        html_body = h_reader_html.wfile.getvalue().decode("utf-8")
        self.assertIn("TANRAIL LIBRARY", html_body)
        self.assertIn("Back to Catalogue", html_body)

        # 3. Student queries /api/reader/info for valid 2-page PDF (Book 1)
        h_info = self.make_handler(f"/api/reader/info?book_id=1&library_id={self.lib1_id}", "GET", token=student_token)
        h_info.do_GET()
        self.assertEqual(h_info.status_code, 200)
        self.assertEqual(h_info.json_response["title"], "TANRAIL Operations Manual")
        self.assertEqual(h_info.json_response["page_count"], 2)
        self.assertEqual(h_info.json_response["branding"]["institution_name"], "TANRAIL LIBRARY")

        # 4. Student renders Page 1 and Page 2 as PNG via /api/reader/page
        h_p1 = self.make_handler(f"/api/reader/page?book_id=1&library_id={self.lib1_id}&page=1&dpi=150", "GET", token=student_token)
        h_p1.do_GET()
        self.assertEqual(h_p1.status_code, 200)
        self.assertEqual(h_p1.sent_headers.get("Content-Type"), "image/png")
        self.assertTrue(h_p1.wfile.getvalue().startswith(b"\x89PNG"))
        self.assertIn("no-store", h_p1.sent_headers.get("Cache-Control", ""))

        # Out-of-bounds page returns 404
        h_p99 = self.make_handler(f"/api/reader/page?book_id=1&library_id={self.lib1_id}&page=99", "GET", token=student_token)
        h_p99.do_GET()
        self.assertEqual(h_p99.status_code, 404)

        # 5. Student searches inside PDF via /api/reader/search
        h_search = self.make_handler(f"/api/reader/search?book_id=1&library_id={self.lib1_id}&q=Locomotive", "GET", token=student_token)
        h_search.do_GET()
        self.assertEqual(h_search.status_code, 200)
        self.assertGreaterEqual(h_search.json_response["total_matches"], 1)
        self.assertEqual(h_search.json_response["results"][0]["page"], 2)

        # 6. HTTP Range Request on /api/reader/stream returns 206 Partial Content
        h_range = self.make_handler(
            f"/api/reader/stream?book_id=1&library_id={self.lib1_id}",
            "GET",
            token=student_token,
            headers={"Range": "bytes=0-63"}
        )
        h_range.do_GET()
        self.assertEqual(h_range.status_code, 206)
        self.assertEqual(h_range.sent_headers.get("Accept-Ranges"), "bytes")
        self.assertTrue(h_range.sent_headers.get("Content-Range", "").startswith("bytes 0-63/"))
        self.assertEqual(len(h_range.wfile.getvalue()), 64)

        # 7. Missing PDF (Book 2 is EPUB-only) -> 404
        h_no_pdf = self.make_handler(f"/api/reader/info?book_id=2&library_id={self.lib1_id}", "GET", token=student_token)
        h_no_pdf.do_GET()
        self.assertEqual(h_no_pdf.status_code, 404)

        # 8. Corrupt PDF (Book 3) -> 422 Unprocessable Entity
        h_corrupt = self.make_handler(f"/api/reader/info?book_id=3&library_id={self.lib1_id}", "GET", token=student_token)
        h_corrupt.do_GET()
        self.assertEqual(h_corrupt.status_code, 422)

        # 9. Path traversal / non-integer book_id -> 400 Bad Request
        h_traversal = self.make_handler(f"/api/reader/info?book_id=../../etc/passwd&library_id={self.lib1_id}", "GET", token=student_token)
        h_traversal.do_GET()
        self.assertEqual(h_traversal.status_code, 400)

        # 10. Unauthorized Library (Student accessing faculty_only library) -> 403 Forbidden
        h_unauth_lib = self.make_handler(f"/api/reader/info?book_id=1&library_id={self.lib2_id}", "GET", token=student_token)
        h_unauth_lib.do_GET()
        self.assertEqual(h_unauth_lib.status_code, 403)

        # Faculty CAN access faculty_only library -> 200 OK
        h_fac_lib = self.make_handler(f"/api/reader/info?book_id=1&library_id={self.lib2_id}", "GET", token=faculty_token)
        h_fac_lib.do_GET()
        self.assertEqual(h_fac_lib.status_code, 200)

        # 11. Download Policy Enforcement: when download_policy='admin_only', Student can still read pages,
        #     but /api/reader/stream is blocked with 403 Forbidden!
        self.cm.update_catalogue_settings(download_policy="admin_only", actor="admin")
        try:
            h_info_restricted = self.make_handler(f"/api/reader/info?book_id=1&library_id={self.lib1_id}", "GET", token=student_token)
            h_info_restricted.do_GET()
            self.assertEqual(h_info_restricted.status_code, 200)
            self.assertFalse(h_info_restricted.json_response["can_download"])

            # Page rendering still works for Student
            h_page_ok = self.make_handler(f"/api/reader/page?book_id=1&library_id={self.lib1_id}&page=1", "GET", token=student_token)
            h_page_ok.do_GET()
            self.assertEqual(h_page_ok.status_code, 200)

            # Raw PDF stream / download is blocked with 403 for Student
            h_stream_blocked = self.make_handler(f"/api/reader/stream?book_id=1&library_id={self.lib1_id}", "GET", token=student_token)
            h_stream_blocked.do_GET()
            self.assertEqual(h_stream_blocked.status_code, 403)

            # Admin can still download
            h_stream_admin = self.make_handler(f"/api/reader/stream?book_id=1&library_id={self.lib1_id}&download=1", "GET", token=admin_token)
            h_stream_admin.do_GET()
            self.assertEqual(h_stream_admin.status_code, 200)
        finally:
            self.cm.update_catalogue_settings(download_policy="authenticated", actor="admin")

    def test_04_loop6_student_permissions_audit_blocks_all_modifications(self):
        """Loop 6: Verify Student is blocked (403) from Convert, Edit, Delete, Upload, Notes, and FTS endpoints."""
        student_token = gateway.create_session("student", "12345678")

        forbidden_routes = [
            ("GET", "/calibre/conversion/book-data/1"),
            ("POST", "/calibre/conversion/start/1"),
            ("GET", "/calibre/conversion/status/1"),
            ("POST", "/calibre/cdb/cmd/delete_books/0"),
            ("POST", "/calibre/cdb/cmd/set_fields/0"),
            ("POST", "/calibre/cdb/add-book/1/0/test.epub"),
            ("POST", "/calibre/cdb/copy-to-library/Other"),
            ("POST", "/calibre/ajax/set-fields/1/Main"),
            ("POST", "/calibre/ajax/delete-books/1/Main"),
            ("POST", "/calibre/set-note/authors/1/Main"),
            ("POST", "/calibre/data-files/upload/1/Main"),
            ("POST", "/calibre/data-files/remove/1/Main"),
            ("POST", "/calibre/fts/disable"),
            ("POST", "/calibre/fts/reindex"),
            ("POST", "/calibre/fts/indexing"),
        ]

        for method, route in forbidden_routes:
            h = self.make_handler(
                route,
                method,
                token=student_token,
                headers={"Origin": "http://127.0.0.1:8085", "Host": "127.0.0.1:8085"},
                body=b"{}" if method == "POST" else b""
            )
            if method == "GET":
                h.do_GET()
            else:
                h.do_POST()
            self.assertEqual(
                h.status_code,
                403,
                f"Expected 403 Forbidden for Student on {method} {route}, got {h.status_code}"
            )

        # Verify injected UI for Student hides .cs-bd-actions and enforces reader-only navigation on /calibre/
        student_session = gateway.get_session(student_token)
        injected_student = gateway.build_injected_institutional_ui(student_session)
        self.assertIn(".cs-bd-actions", injected_student)
        self.assertIn("display: none !important", injected_student)
        self.assertIn("enforceReaderOnlyNavigation", injected_student)
        self.assertNotIn("inst-nav-admin-btn", injected_student)

        # Verify Admin injected UI includes Admin Console button and does NOT block native Calibre panels
        admin_token = gateway.create_session("admin", "adminpass")
        admin_session = gateway.get_session(admin_token)
        injected_admin = gateway.build_injected_institutional_ui(admin_session)
        self.assertIn("inst-nav-admin-btn", injected_admin)
        self.assertNotIn("enforceReaderOnlyNavigation", injected_admin)


if __name__ == "__main__":
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ClientFeedbackV2Tests)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        if not result.wasSuccessful():
            sys.exit(1)
    finally:
        TEST_ENV_DIR.cleanup()
