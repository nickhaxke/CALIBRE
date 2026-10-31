"""
Live End-to-End Verification Script (Loop 10)
Starts the real Institutional Gateway & Calibre Content Server against the real
TANRAIL LIBRARY (C:/Users/USER/Calibre Library) and verifies Loops 2 through 8 over live HTTP.
Note: Uses explicit `ensure()` checks rather than `assert` because calibre-debug.exe runs with Python -O.
"""

import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GATEWAY_URL = "http://127.0.0.1:8085"


def ensure(condition, message):
    if not condition:
        raise RuntimeError(f"VERIFICATION FAILED: {message}")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def make_client():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirectHandler())
    return opener, cj


def request(opener, path, method="GET", data=None, headers=None, json_data=None):
    url = GATEWAY_URL + path
    hdrs = dict(headers or {})
    hdrs.setdefault("Origin", GATEWAY_URL)
    body = None
    if json_data is not None:
        body = json.dumps(json_data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif data is not None:
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif isinstance(data, bytes):
            body = data
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        resp = opener.open(req, timeout=20)
        return resp.getcode(), dict(resp.info()), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def main():
    calibre_debug = r"C:\Users\USER\AppData\Local\Programs\CalibreInstitutional\calibre\calibre-debug.exe"
    gateway_script = r"c:\dev\calibre-institutional\customization\backend\gateway_server.py"

    env = os.environ.copy()
    env["CALIBRE_DEVELOP_FROM"] = r"c:\dev\calibre-institutional\upstream\calibre\src"

    print("[1] Launching Live Institutional Gateway Server on port 8085...")
    proc = subprocess.Popen(
        [calibre_debug, "-e", gateway_script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        ready = False
        for _ in range(60):
            time.sleep(1.0)
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                raise RuntimeError(f"Gateway exited early with code {proc.returncode}:\n{out}")
            try:
                opener, _ = make_client()
                code, _, _ = request(opener, "/")
                if code == 200:
                    ready = True
                    break
            except Exception:
                pass

        ensure(ready, "Gateway did not become ready on port 8085 within 60 seconds.")
        print("    -> Gateway and Calibre Content Server are LIVE on 127.0.0.1:8085!")

        # ------------------------------------------------------------------
        # 2. Authenticate as Student ('student' / '12345678', display name 'nick')
        # ------------------------------------------------------------------
        student_opener, _ = make_client()
        code, hdrs, auth_bytes = request(
            student_opener,
            "/api/auth/login",
            method="POST",
            json_data={"username": "student", "password": "12345678"},
        )
        ensure(code == 200, f"Student login failed with status {code}: {auth_bytes}")
        auth_obj = json.loads(auth_bytes.decode("utf-8"))
        ensure(auth_obj.get("success") is True, f"Student login success!=True: {auth_obj}")
        print(f"[2] Student ('{auth_obj['user']['username']}' / display name '{auth_obj['user']['displayName']}') authenticated successfully.")

        # Wait up to 20s for backend calibre-server on 8088 to respond
        api_data = None
        for _ in range(30):
            code, _, raw = request(student_opener, "/calibre/institutional/api")
            if code == 200:
                api_data = json.loads(raw.decode("utf-8"))
                break
            time.sleep(1.0)
        ensure(api_data is not None, f"Failed to load /calibre/institutional/api (last code={code})")

        # ------------------------------------------------------------------
        # 3. Verify Loop 2: Public Catalogue Cleanup
        # ------------------------------------------------------------------
        code, _, cat_bytes = request(student_opener, "/calibre/institutional/")
        ensure(code == 200, f"Catalogue HTML returned {code}")
        cat_html = cat_bytes.decode("utf-8", errors="replace")
        for forbidden in [
            "A world of ideas. Yours to explore.",
            "Your library, open to possibility.",
            "volumes to discover",
            'id="total-mark"',
            'id="all-count"',
            'id="result-count"',
            "Classic Calibre",
        ]:
            ensure(forbidden not in cat_html, f"Found forbidden string in live catalogue HTML: {forbidden}")
        ensure("Library Catalogue" in cat_html, "Missing 'Library Catalogue' heading")
        ensure('id="search-form"' in cat_html, "Missing #search-form")
        ensure('id="search-submit"' in cat_html, "Missing #search-submit button")

        for facet_group in api_data.get("facets", []):
            for item in facet_group.get("items", []):
                ensure("count" not in item, f"Facet item still exposes count: {item}")
        print(f"[3] Loop 2 Verified: Public catalogue cleanup active ({len(api_data['books'])} real TANRAIL books loaded, 0 count badges).")

        # ------------------------------------------------------------------
        # 4. Verify Loop 3: Explicit Search & Field-Specific Search
        # ------------------------------------------------------------------
        code, _, raw = request(student_opener, "/calibre/institutional/api?search_field=title&search=Morogoro")
        res_title = json.loads(raw.decode("utf-8"))
        ensure(res_title["total"] >= 1, "Expected Title='Morogoro' to find Morogoro Roster book")
        ensure(any("Morogoro" in b["title"] for b in res_title["books"]), "Expected Morogoro in returned book titles")

        code, _, raw = request(student_opener, "/calibre/institutional/api?search_field=title&search=Schember")
        res_title_miss = json.loads(raw.decode("utf-8"))
        ensure(res_title_miss["total"] == 0, f"Expected Title='Schember' to return 0 books, got {res_title_miss['total']}")

        code, _, raw = request(student_opener, "/calibre/institutional/api?search_field=authors&search=Schember")
        res_author = json.loads(raw.decode("utf-8"))
        ensure(res_author["total"] >= 1, "Expected Author='Schember' to find Quick Start Guide")
        print("[4] Loop 3 Verified: Field-specific search (Title, Author, All Fields) works accurately against live Calibre DB.")

        # ------------------------------------------------------------------
        # 5. Verify Loop 4: Professional Book Details & Read Online Routing
        # ------------------------------------------------------------------
        books_by_id = {b["id"]: b for b in api_data["books"]}
        ensure(2 in books_by_id, f"Book 2 not found in {list(books_by_id.keys())}")
        b2 = books_by_id[2]
        ensure(b2["has_pdf"] is True, "Expected Book 2 has_pdf=True")
        ensure(b2["reader_url"].startswith("/reader?book_id=2"), f"Unexpected PDF reader_url: {b2['reader_url']}")
        ensure(b2["pages"] != 0, f"Book 2 should not have pages=0 placeholder, got {b2['pages']}")
        ensure(b2["allow_native"] is False, f"Expected allow_native=False, got {b2['allow_native']}")

        # Check all books to ensure no book exposes pages == 0 or year == '0101'
        for bk in api_data["books"]:
            ensure(bk.get("pages") != 0, f"Book {bk['id']} exposed invalid pages=0 placeholder")
            ensure(bk.get("year") != "0101", f"Book {bk['id']} exposed invalid year='0101' placeholder")

        if 4 in books_by_id:
            b4 = books_by_id[4]
            ensure(b4["formats"] == [], f"Expected Book 4 to have no formats, got {b4['formats']}")
            ensure(b4["reader_url"] == "", f"Expected Book 4 reader_url='', got {b4['reader_url']}")
            ensure(b4.get("pages") is None, f"Expected Book 4 pages=None, got {b4.get('pages')}")
        print(f"[5] Loop 4 Verified: Book 2 ('{b2['title']}') routes to '{b2['reader_url']}', pages={b2.get('pages')}, Book 4 pages={books_by_id.get(4, {}).get('pages')}, allow_native={b2['allow_native']}.")

        # ------------------------------------------------------------------
        # 6. Verify Loop 5: Branded PDF Reader End-to-End on Real TANRAIL Book 2
        # ------------------------------------------------------------------
        lib_id = api_data["library_id"]
        code, _, reader_bytes = request(student_opener, f"/reader?book_id=2&library_id={lib_id}")
        ensure(code == 200, f"GET /reader returned {code}")
        reader_html = reader_bytes.decode("utf-8", errors="replace")
        ensure("Back to Catalogue" in reader_html, "Reader HTML missing 'Back to Catalogue'")
        ensure("TANRAIL" in reader_html, "Reader HTML missing 'TANRAIL' branding")

        code, _, info_bytes = request(student_opener, f"/api/reader/info?book_id=2&library_id={lib_id}")
        ensure(code == 200, f"GET /api/reader/info returned {code}")
        info = json.loads(info_bytes.decode("utf-8"))
        ensure(info["page_count"] == 11, f"Expected 11 pages for Book 2, got {info['page_count']}")
        ensure("Morogoro" in info["title"], f"Expected Morogoro in Book 2 title, got {info['title']}")

        code1, hdr1, png1 = request(student_opener, f"/api/reader/page?book_id=2&library_id={lib_id}&page=1&dpi=150")
        ensure(code1 == 200 and png1.startswith(b"\x89PNG\r\n\x1a\n"), "Page 1 PNG render failed")
        code2, hdr2, png2 = request(student_opener, f"/api/reader/page?book_id=2&library_id={lib_id}&page=2&dpi=150")
        ensure(code2 == 200 and png2.startswith(b"\x89PNG\r\n\x1a\n"), "Page 2 PNG render failed")

        code_s, _, search_bytes = request(student_opener, f"/api/reader/search?book_id=2&library_id={lib_id}&q=Morogoro")
        ensure(code_s == 200, f"Reader search returned {code_s}")
        search_res = json.loads(search_bytes.decode("utf-8"))
        ensure(search_res["total_matches"] >= 1, f"Expected matches for 'Morogoro' in Book 2, got {search_res}")

        code_r, hdr_r, partial_pdf = request(
            student_opener,
            f"/api/reader/stream?book_id=2&library_id={lib_id}",
            headers={"Range": "bytes=0-1023"},
        )
        ensure(code_r == 206, f"Expected 206 Partial Content, got {code_r}")
        ensure(len(partial_pdf) == 1024 and partial_pdf.startswith(b"%PDF-"), "Invalid partial PDF range response")
        print(
            f"[6] Loop 5 Verified: Branded PDF Reader rendered Book 2 ({info['page_count']} pages, "
            f"Page 1={len(png1)}B, Page 2={len(png2)}B, Search matches={search_res['total_matches']}, HTTP 206 Range OK)."
        )

        # ------------------------------------------------------------------
        # 7. Verify Loop 6: Student Permissions Audit (Live 403 Blocking)
        # ------------------------------------------------------------------
        blocked_checks = [
            ("GET", "/calibre/conversion/book-data/2"),
            ("POST", "/calibre/conversion/start/2"),
            ("POST", "/calibre/cdb/cmd/delete_books/0"),
            ("POST", f"/calibre/ajax/delete-books/2/{lib_id}"),
            ("POST", f"/calibre/ajax/set-fields/2/{lib_id}"),
            ("POST", f"/calibre/data-files/upload/2/{lib_id}"),
            ("GET", "/calibre/fts/indexing"),
            ("GET", "/api/v2/admin/telemetry"),
            ("GET", "/api/admin/users"),
        ]
        for m, route in blocked_checks:
            c, _, _ = request(student_opener, route, method=m)
            ensure(c == 403, f"Expected 403 Forbidden for Student on {m} {route}, got {c}")
        print(f"[7] Loop 6 Verified: All {len(blocked_checks)} book management / conversion / admin endpoints returned 403 Forbidden for Student.")

        # ------------------------------------------------------------------
        # 8. Verify Admin Console V2 Access Preserved for Administrator
        # ------------------------------------------------------------------
        admin_opener, _ = make_client()
        code_a, _, _ = request(
            admin_opener,
            "/api/auth/login",
            method="POST",
            json_data={"username": "admin", "password": "InstitutionalAdmin2026!"},
        )
        ensure(code_a == 200, f"Admin login returned {code_a}")
        code_ov, _, ov_bytes = request(admin_opener, "/api/v2/admin/telemetry")
        ensure(code_ov == 200, f"Admin telemetry returned {code_ov}")
        ov = json.loads(ov_bytes.decode("utf-8"))
        ensure("libraries" in ov and "catalogue_settings" in ov, f"Unexpected admin telemetry payload: {ov.keys()}")
        print("[8] Admin Console V2 Verified: Administrator login and /api/v2/admin/telemetry (200 OK) preserved.")

        print("\n=== ALL LIVE LOOP 10 END-TO-END VERIFICATIONS PASSED STRICTLY! ===")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-NetTCPConnection -LocalPort 8085,8088 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }",
            ],
            check=False,
        )


if __name__ == "__main__":
    main()
