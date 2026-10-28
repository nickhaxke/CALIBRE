# Targeted Bug Investigation & Resolution: Calibre Gateway Logout

**Investigation Reference:** `CALIBRE-SEC-BUG-001`  
**Application:** Institutional Calibre Digital Library Gateway  
**Environment:** Windows Host / Python 3.14 / Calibre Core Engine v9.17.0  
**Target Endpoint:** `http://127.0.0.1:8085/calibre/`  
**Classification:** Authentication & Session Management Defect  

---

## 1. Executive Summary

When patrons authenticated as `student1` on the institutional portal and entered the proxied Calibre library (`http://127.0.0.1:8085/calibre/`), clicking Calibre's native top-bar user menu opened a dialog displaying:
> *"You are logged in as the user student1. To log in as a different user, you will have to restart the browser."*

Users found no functional Sign Out action anywhere inside the proxied Calibre interface, and could not switch user accounts without terminating the host browser process.

### Outcome of Investigation & Fix
A complete, non-invasive architectural resolution was designed, implemented, and verified:
1. **Prominent Institutional Sign Out Control:** Injected a sleek, responsive, institutional top navigation bar (`#inst-calibre-nav`) anchored to the top of all proxied Calibre views with institutional branding, patron identity badge (`Alex Rivera (student1 — Student)`), "Portal Home" navigation, and a prominent red "Sign Out" button.
2. **Calibre Native Dialog Enhancement:** Implemented a lightweight client-side `MutationObserver` that intercepts Calibre's native user dialog, replaces the confusing "restart the browser" message with an institutional notice, and injects a prominent **"Sign Out of Institutional Library"** button directly into the dialog's action container.
3. **Session Invalidation & Cookie Expiration:** Calling Sign Out terminates the server-side gateway session in memory, expires the `inst_session_id` cookie (`Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT`), and redirects to the landing page.
4. **BFCache & Back-Button Defense:** Enforced strict HTTP anti-caching headers (`Cache-Control: no-store, no-cache, must-revalidate, private, max-age=0`, `Pragma: no-cache`, `Expires: 0`) and client-side `pageshow` session validation, preventing browser history back-navigation from restoring protected library content.
5. **Zero Upstream Modifications:** Upstream Calibre source code (`upstream/calibre`) and host production Calibre files (`C:\Program Files\Calibre2`) remain 100% untouched.
6. **Comprehensive Verification:** 19/19 automated test cases pass (`tests/test_logout_security.py` and `tests/test_gateway_mvp.py`), plus full end-to-end automated verification inside real Google Chrome via Chrome DevTools Protocol (CDP).

---

## 2. Root Cause Analysis

Investigation of [gateway_server.py](file:///C:/dev/calibre-institutional/customization/backend/gateway_server.py), [home.pyj](file:///C:/dev/calibre-institutional/upstream/calibre/src/pyj/book_list/home.pyj#L386-L405), and Calibre's client-side SPA identified four contributing factors:

### Cause 1: Calibre's Native HTTP Basic Authentication Assumption
Calibre Content Server was originally architected for direct, unproxied client-to-server HTTP Basic (or Digest) authentication. Under RFC 7617 HTTP Basic authentication, web browsers store credentials in an internal memory cache for the lifetime of the browser process. Because standard HTTP has no logout command for HTTP Basic auth, Calibre's front-end developers hard-coded the following logic in [upstream/calibre/src/pyj/book_list/home.pyj](file:///C:/dev/calibre-institutional/upstream/calibre/src/pyj/book_list/home.pyj#L386-L405):

```python
def show_user_details():
    interface_data = get_interface_data()
    create_custom_dialog(_('Logged in as {}').format(interface_data.username), def (parent, close_modal):
        msg = E.div()
        safe_set_inner_html(msg, _(
            'You are logged in as the user <b>{}</b>. To log in '
            'as a different user, you will have to restart the browser.').format(interface_data.username))
        parent.appendChild(msg)
        parent.appendChild(
            E.div(class_='button-box',
                create_button(_('Close'), None, close_modal),
                create_button(_('Change password'), None, def ():
                    setTimeout(change_password, 0)
                    close_modal()
                , highlight = True),
            )
        )
    )
```

### Cause 2: Architectural Gap in the Reverse Proxy
In our institutional architecture, the web browser **never** holds HTTP Basic credentials. The browser authenticates via a session cookie (`inst_session_id`). The Gateway verifies the cookie and injects `Authorization: Basic ...` upstream to loopback Calibre (`127.0.0.1:8088`).  
However, the gateway initially served Calibre's full-screen SPA HTML (`index-generated.html`) verbatim. The user was trapped inside Calibre's full-screen layout with zero institutional controls.

### Cause 3: Bundled JavaScript String Literal Collisions
Calibre embeds its compiled RapydScript JavaScript bundle directly inside `index-generated.html` (3.9 MB). This bundle contains client-side HTML templates with string literals like:
`"text-align:center\">\n__BS__\n</div>\n</body>\n</html>\n".replace(...)`  
A standard string `replace("</body>", ...)` replaces the **first** occurrence inside a JavaScript string literal at byte 548,854, breaking Calibre's script execution with syntax errors. The real document closing tag is at byte 3,962,405 and must be targeted via `rfind("</body>")`.

### Cause 4: Upstream HTTP Gzip Compression
Modern browsers send `Accept-Encoding: gzip, deflate, br`. When proxied without header sanitization, Calibre returns compressed binary bytes (`\x1f\x8b`). Trying to string-decode or inject into gzipped bytes corrupts the stream and causes the browser to stall in `readyState=loading`.

---

## 3. Architecture of the Fix

```
+-----------------------------------------------------------------------------------+
| Institutional Gateway Reverse Proxy (Port 8085)                                  |
|                                                                                   |
|  1. Incoming Request -> Check Cookie 'inst_session_id' -> SESSIONS Store         |
|  2. If Invalid/Logged Out -> Redirect 302 to /?login_required=1 (Anti-cache)       |
|  3. Forward to Upstream Calibre (127.0.0.1:8088) with User's Basic Auth          |
|  4. Upstream Response: Transparent Gzip Decompress + Strip Content-Encoding       |
|  5. If Content-Type == text/html:                                                 |
|     - Locate TRUE document closing tag via rfind('</body>')                       |
|     - Inject:                                                                     |
|       * Fixed Institutional Top Bar (#inst-calibre-nav)                           |
|       * Layout Offset Styles (body { margin-top: 44px !important })               |
|       * Unified performInstitutionalSignOut() JavaScript Bridge                   |
|       * BFCache pageshow Listener (forces redirect if unauthenticated)            |
|       * DOM MutationObserver (patches native Calibre user dialog)                 |
|  6. Apply strict anti-caching: Cache-Control: no-store, no-cache, must-revalidate   |
+-----------------------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------------------+
| Client Web Browser (Chrome / Edge / Firefox)                                      |
|                                                                                   |
|  [AIT | Aethelgard Institute] [Alex Rivera (student1 - Student)] [Home] [Sign Out] |
|  -------------------------------------------------------------------------------  |
|  (Calibre Content Server SPA rendered cleanly below the institutional top bar)    |
|                                                                                   |
|  * Clicking "Sign Out" -> POST /api/auth/logout -> Session Destroyed -> /         |
|  * Opening Calibre Dialog -> Dialog intercepted: Sign Out button injected!        |
|  * Browser Back Button -> BFCache pageshow handler blocks re-entry -> Deflected   |
+-----------------------------------------------------------------------------------+
```

---

## 4. Files Modified

| File | Nature of Changes | Clickable Path |
| :--- | :--- | :--- |
| `gateway_server.py` | UI injection via `rfind('</body>')`, transparent gzip decompression, `apply_no_cache_headers()`, GET and POST `/api/auth/logout` handlers | [gateway_server.py](file:///C:/dev/calibre-institutional/customization/backend/gateway_server.py) |
| `portal.js` | Synchronized `checkUrlParams()`, dynamic alert rendering for `?logged_out=1` and `?login_required=1`, URL cleanup | [portal.js](file:///C:/dev/calibre-institutional/customization/frontend/static/js/portal.js) |
| `portal.css` | Status alert `.status-alert.logged-out` visual styling | [portal.css](file:///C:/dev/calibre-institutional/customization/frontend/static/css/portal.css) |
| `test_logout_security.py` | Comprehensive regression suite covering logout, anti-caching, session isolation, user switching | [test_logout_security.py](file:///C:/dev/calibre-institutional/tests/test_logout_security.py) |
| `verify_browser_journey.py` | Real Google Chrome CDP automated user journey verification script | [verify_browser_journey.py](file:///C:/Users/USER/.gemini/antigravity-ide/brain/05a9a911-d679-490a-8d1b-5db3c60cb8fb/scratch/verify_browser_journey.py) |

---

## 5. Security & Regression Verification Results

### Test Suite 1: Security & Regression Suite (`tests/test_logout_security.py`)
Ran 9 comprehensive automated test cases against `http://127.0.0.1:8085`:

| # | Test Case Description | Verified Behavior | Status |
| :-: | :--- | :--- | :-: |
| 1 | `test_01_landing_page_anti_cache` | Strict `no-store, no-cache, must-revalidate` on landing page | **PASS** |
| 2 | `test_02_unauthenticated_calibre_redirect` | Direct unauthenticated access to `/calibre/` redirects (302) to `/?login_required=1` | **PASS** |
| 3 | `test_03_unauthenticated_api_and_book_rejection` | Direct access to `/calibre/ajax/books` and `/calibre/get/epub/1/library` returns 401 | **PASS** |
| 4 | `test_04_student_login_and_ui_injection` | `#inst-calibre-nav`, user name, role, Sign Out button, and `MutationObserver` present in HTML | **PASS** |
| 5 | `test_05_ajax_logout_invalidates_session_and_expires_cookie` | POST `/api/auth/logout` destroys session, sets `Max-Age=0; Expires=1970`, rejects subsequent book access | **PASS** |
| 6 | `test_06_direct_get_logout_redirect` | GET `/api/auth/logout` invalidates session and redirects 302 to `/?logged_out=1` | **PASS** |
| 7 | `test_07_immediate_user_switch_without_browser_restart` | Student signs out -> Faculty immediately signs in in same client -> Faculty identity displayed | **PASS** |
| 8 | `test_08_multiple_concurrent_sessions_isolation` | Logging out session A (student) leaves session B (librarian) completely valid and active | **PASS** |
| 9 | `test_09_no_credentials_leakage` | No password, hash, or Basic Auth token ever present in client-facing HTML or JSON | **PASS** |

### Test Suite 2: MVP Gateway Baseline Suite (`tests/test_gateway_mvp.py`)
Verified 10/10 existing gateway functional tests continue to pass without regression:
- Landing page serving: **PASS**
- Unauthenticated API protection: **PASS**
- Browser redirect: **PASS**
- LAN loopback port isolation (8088 blocked remotely): **PASS**
- Credential validation: **PASS**
- Patron identity resolution: **PASS**
- Catalog browsing: **PASS**
- EPUB reader streaming: **PASS**
- LAN IP connectivity: **PASS**
- Session destruction: **PASS**

### Test Suite 3: End-to-End Browser User Journey via Google Chrome CDP
Executed full journey automation with real Google Chrome (Version 155):
1. **Landing Page:** Verified title, institutional seal, and Guest state (`step1_landing_guest.png`).
2. **Authentication:** Authenticated as `student1` / `StudentPass123!`; verified UI updated with patron badge (`step2_landing_authenticated.png`).
3. **Calibre Navigation:** Loaded `http://127.0.0.1:8085/calibre/`; verified `#inst-calibre-nav` is visible, displays `Alex Rivera (Student ID: #8841) (Student)`, and offset `margin-top: 44px` is applied (`step3_calibre_with_institutional_bar.png`).
4. **Calibre Native Dialog:** Triggered native user dialog; verified `MutationObserver` replaced message with institutional text and injected red `Sign Out of Institutional Library` button (`step4_calibre_dialog_enhanced.png`).
5. **Sign Out:** Clicked Sign Out; verified redirection to `/?logged_out=1`, session terminated, cookie cleared, and green "Signed Out" alert rendered (`step5_post_logout_landing.png`).
6. **Browser Back Button:** Executed `window.history.back()`; verified browser was blocked and deflected back to landing page; zero protected library content exposed (`step6_back_button_deflected.png`).
7. **Switching Users:** Immediately authenticated as `faculty1` / `FacultyPass123!` without restarting browser; loaded `/calibre/`; verified patron badge displays `Prof. Elena Rostova (Dept. of Computing) (Faculty)` (`step7_faculty_authenticated_in_calibre.png`).

---

## 6. Safety & Boundary Adherence

| Asset / Constraint | Verification |
| :--- | :--- |
| `C:\Program Files\Calibre2\` | Untouched. Checked file timestamps and hashes. |
| Production Library (`C:\Users\USER\Calibre Library`) | Untouched. Verified `metadata.db` integrity. |
| Upstream Calibre Source (`upstream/calibre`) | Untouched. 0 lines modified. |
| Production Service (Port 8080) | Untouched. Running continuously on PID 23128. |
| Test Environment Isolation | All work isolated to `C:\dev\calibre-institutional\` (Ports 8085, 8088). |

---

## 7. Remaining Limitations & Recommendations

1. **Native EPUB Reader Top Bar:** In Calibre's standalone in-browser EPUB reader window (`/calibre/#book_id=...&panel=read_book`), the reader renders inside a dedicated container element. The injected top bar is visible above the reader, but full-screen toggle mode (`F11` inside reader) hides external DOM elements by design. A keyboard shortcut (e.g. `Ctrl+Q` or `Escape`) or floating overlay could be added for readers reading in full-screen distraction-free mode.
2. **Session Idle Timeout:** Currently set to 8 hours (28,800 seconds) in `gateway_config.json`. For public campus terminals, a configurable idle warning (e.g., 15 minutes of inactivity prompting a sign-out countdown modal) is recommended before general campus deployment.
