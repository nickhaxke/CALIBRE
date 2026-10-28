# Phase 2 — Security Audit Report: Institutional Calibre Gateway
**Document Reference:** SEC-AUDIT-PHASE2-001  
**Project:** Institutional Calibre Digital Library  
**Date:** October 27, 2026  
**Auditor:** Principal Software Architect & Python Security Engineer  
**Scope:** `customization/backend/gateway_server.py`, `customization/frontend/static/js/portal.js`, `customization/configuration/gateway_config.json`, `test-environment/config/server-users.sqlite`, and test suites.

---

## 1. Executive Summary

A comprehensive architectural and application-security audit was conducted on the Phase 1 prototype of the Calibre Institutional Gateway. The audit identified six (6) security vulnerabilities and architectural risks, ranging from **Critical** to **Low**. 

The most critical defect was the persistence of hardcoded administrative credentials (`student1:StudentPass123!`) in `gateway_server.py:serve_catalog()`, which bypassed authentication and permitted unauthenticated patrons to browse repository metadata under a fixed identity. In addition, the gateway was vulnerable to path traversal attacks against static assets, lacked brute-force protection (rate limiting) on the primary login endpoint, stored unencrypted HTTP Basic authentication credentials in process memory, omitted Cross-Site Request Forgery (CSRF) header validation, and leaked internal stack/exception strings to clients during upstream outages.

This document classifies each finding, provides reproduction evidence, identifies root causes, and outlines the required hardening remediations for Phase 2 implementation.

---

## 2. Vulnerability Classification Matrix

| Finding ID | Severity | Category | Target Component | Status |
| :--- | :--- | :--- | :--- | :--- |
| **VULN-01** | **CRITICAL** | Hardcoded Credentials & Auth Bypass | `gateway_server.py` (`serve_catalog`) | Verified / Open |
| **VULN-02** | **HIGH** | Missing Rate Limiting / Brute Force | `gateway_server.py` (`do_POST /api/auth/login`) | Verified / Open |
| **VULN-03** | **HIGH** | Path Traversal Vulnerability | `gateway_server.py` (`serve_static`) | Verified / Open |
| **VULN-04** | **MEDIUM** | In-Memory Plaintext Credential Retention | `gateway_server.py` (`SESSIONS` dict) | Verified / Open |
| **VULN-05** | **MEDIUM** | Missing CSRF Origin/Referer Validation | `gateway_server.py` (`do_POST` handlers) | Verified / Open |
| **VULN-06** | **LOW** | Information Disclosure in Error Handlers | `gateway_server.py` (500/502 handlers) | Verified / Open |

---

## 3. Detailed Vulnerability Analyses

### VULN-01: Hardcoded Credentials & Unauthenticated Catalog Access
- **Severity:** **CRITICAL** (CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N - Base Score: 7.5)
- **Location:** `customization/backend/gateway_server.py`, lines 562–583.
- **Description:** 
  The endpoint `/api/catalog` did not inspect incoming session tokens or verify patron identity. Instead, it generated a static Base64 authorization header using hardcoded credentials:
  ```python
  def serve_catalog(self):
      url = f"{BACKEND_URL}/ajax/books"
      req = urllib.request.Request(url)
      # Use student1 internal credentials to query the catalog structure
      b64 = base64.b64encode(b"student1:StudentPass123!").decode("ascii")
      req.add_header("Authorization", f"Basic {b64}")
  ```
- **Security Impact:**
  1. Any guest or unauthenticated network client on the LAN could retrieve the library catalog without credentials.
  2. The catalog view was strictly bound to `student1`. Patrons with elevated access (faculty, librarians) or specific tag restrictions (restricted students) were presented with `student1`'s catalog rather than their own authorization context.
  3. Hardcoded passwords in application logic violate institutional compliance and zero-trust standards.
- **Remediation Plan:**
  - Enforce session authentication on `/api/catalog`. Unauthenticated requests must receive HTTP 401 Unauthorized.
  - Utilize the authenticated user's session credentials (`session['basic_auth']`) to query upstream Calibre, ensuring per-user library restrictions and tag visibility rules are respected.
  - Remove all hardcoded credentials from source code and static templates (`index.html`).

---

### VULN-02: Absence of Login Rate Limiting (Brute-Force Exposure)
- **Severity:** **HIGH** (CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:L/A:N - Base Score: 8.2)
- **Location:** `customization/backend/gateway_server.py`, lines 480–511.
- **Description:**
  The `/api/auth/login` endpoint processed unlimited authentication attempts without throttling or IP-based lockouts. Verification tests confirmed that 100+ rapid authentication attempts per second were processed sequentially with HTTP 401 responses, enabling automated dictionary and credential stuffing attacks against student, faculty, and administrator accounts.
- **Security Impact:**
  Patron and administrative accounts could be compromised via brute-force dictionary attacks over LAN or campus Wi-Fi.
- **Remediation Plan:**
  - Implement a thread-safe sliding-window rate limiter in `gateway_server.py`.
  - Restrict failed login attempts to a maximum of 5 attempts per 60-second window per client IP.
  - Return HTTP 429 Too Many Requests with a `Retry-After: 60` header when the threshold is exceeded.
  - Reset the counter upon successful authentication.

---

### VULN-03: Arbitrary File Read / Path Traversal in Static Asset Handler
- **Severity:** **HIGH** (CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N - Base Score: 7.5)
- **Location:** `customization/backend/gateway_server.py`, lines 544–561.
- **Description:**
  The `serve_static` method resolved requested paths using simple string concatenation without validating that the canonical target path remained within the designated `STATIC_DIR`:
  ```python
  def serve_static(self, path, head_only=False):
      relpath = path[len("/static/"):].replace("/", os.sep)
      fullpath = os.path.join(STATIC_DIR, relpath)
  ```
  Requests containing dot-dot-slash sequences (`/static/../../configuration/gateway_config.json`) could potentially traverse outside `customization/frontend/static`.
- **Security Impact:**
  Unauthorized retrieval of internal server configuration, user databases, or sensitive operating system files.
- **Remediation Plan:**
  - Canonicalize the path using `os.path.realpath(fullpath)`.
  - Enforce boundary validation: `os.path.commonpath([STATIC_DIR, canonical_path]) == STATIC_DIR`.
  - Immediately return HTTP 404 or 403 if traversal is detected.

---

### VULN-04: Plaintext In-Memory Credential Retention
- **Severity:** **MEDIUM** (CVSS:3.1/AV:L/AC:L/PR:H/UI:N/S:U/C:H/I:N/A:N - Base Score: 4.4)
- **Location:** `customization/backend/gateway_server.py`, lines 41–65.
- **Description:**
  To satisfy upstream Calibre's HTTP Basic Authentication requirement on every proxied request, the gateway retained `basic_auth` (plaintext base64 `username:password`) in the process memory `SESSIONS` dictionary for the duration of the session (up to 8 hours).
- **Security Impact:**
  A process memory dump, core dump, or arbitrary memory read vulnerability could expose cleartext credentials of all active users, including administrative librarians.
- **Remediation Plan:**
  - Audit all loggers to ensure `session['basic_auth']` and `Authorization` headers are never written to disk or standard output.
  - Implement explicit memory sanitization upon session termination (`destroy_session()`).
  - Document architectural necessity for Phase 2/3 (upstream Calibre HTTP server requires Basic Auth per request; no session token exchange API exists upstream).

---

### VULN-05: Missing CSRF Origin and Referer Validation
- **Severity:** **MEDIUM** (CVSS:3.1/AV:N/AC:M/PR:N/UI:R/S:U/C:N/I:L/A:L - Base Score: 5.4)
- **Location:** `customization/backend/gateway_server.py`, `do_POST` handlers.
- **Description:**
  State-changing POST endpoints (`/api/auth/login`, `/api/auth/logout`) did not inspect `Origin` or `Referer` headers. A malicious site loaded in another tab could send cross-site requests to forge login or cause forced logout (denial of service).
- **Security Impact:**
  Cross-site request forgery attacks resulting in forced patron logout or credential submission.
- **Remediation Plan:**
  - Enforce `SameSite=Lax` on session cookies.
  - Inspect `Origin` and `Referer` headers on all POST requests. If present, verify they match the gateway's configured host or loopback address. Reject untrusted cross-origin POSTs with HTTP 403 Forbidden.

---

### VULN-06: Internal Error Message & Trace Information Disclosure
- **Severity:** **LOW** (CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N - Base Score: 5.3)
- **Location:** `customization/backend/gateway_server.py`, lines 582 and 701.
- **Description:**
  When upstream connections failed, the gateway directly interpolated Python exception messages into client HTTP responses:
  ```python
  self.send_json(500, {"error": f"Failed to fetch catalog: {e}"})
  self.send_error(502, f"Gateway Error connecting to Calibre engine: {e}")
  ```
- **Security Impact:**
  Internal IP addresses, port numbers, local file system paths, and Python stack diagnostics could be revealed to untrusted clients.
- **Remediation Plan:**
  - Replace raw exception strings in HTTP responses with generic, user-safe messages: `"Institutional repository service temporarily unavailable."`
  - Log diagnostic details securely to server stderr/stdout with timestamp and error ID.

---

## 4. Frontend & Template Audit Findings

1. **Hardcoded Demo Accounts in `index.html`:**
   Lines 96–101 contained pre-filled credential buttons:
   ```html
   <button type="button" class="btn-chip" onclick="fillCredentials('student1', 'StudentPass123!')">student1 (Student)</button>
   <button type="button" class="btn-chip" onclick="fillCredentials('faculty1', 'FacultyPass123!')">faculty1 (Faculty)</button>
   <button type="button" class="btn-chip" onclick="fillCredentials('librarian1', 'LibAdminPass123!')">librarian1 (Admin)</button>
   ```
   These demo helper buttons must be removed from production/runtime templates. The UI layout and aesthetics must remain strictly intact as instructed.

2. **Client-Side Session State Handling in `portal.js`:**
   The client-side `loadCatalog()` function assumed that the catalog could be fetched unconditionally. With the fix for VULN-01, `loadCatalog()` must gracefully handle 401 responses when the patron is unauthenticated, rendering an institutional "Authentication Required to View Collection" state rather than an error banner.

---

## 5. Architectural Verification: Calibre User Permissions & Restrictions

Audit of the SQLite user database (`test-environment/config/server-users.sqlite`) confirmed:
- `student1`: Role Student, Readonly `y`, Restriction `""`.
- `faculty1`: Role Faculty, Readonly `y`, Restriction `""`.
- `librarian1`: Role Administrator, Readonly `n`, Restriction `""`.

Calibre's Content Server enforces user restrictions at the query engine level using Calibre search expressions (e.g., `tag:public`, `not tag:confidential`). When requests are proxied with the user's authentic Basic Auth header, Calibre filters both the JSON search endpoints (`/ajax/books`) and the reader views automatically. 

By removing the hardcoded `student1` header and forwarding the authenticated user's credentials on all calls to `/ajax/books` and `/calibre/*`, full institutional authorization and library segregation are achieved.

---

## 6. Audit Conclusion & Next Steps

The Phase 1 architecture is sound in its reverse-proxy pattern, session lifecycle, and responsive UI injection, but required targeted security hardening before library integration testing. All six identified vulnerabilities will be remedied in Step 2 and validated through comprehensive automated regression testing in Step 3.
