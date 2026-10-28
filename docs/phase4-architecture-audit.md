# Phase 4 — Architecture & Readiness Audit: Institutional Configuration & Administration
**Document Reference:** ARCH-AUDIT-PHASE4-001  
**Project:** Calibre Institutional Digital Library  
**Date:** October 27, 2026  
**Auditor:** Principal Software Architect, Windows Application Engineer & Security Lead  
**Scope:** Gateway server, authentication & session management, configuration persistence, Calibre backend integration, user database & permissions, multi-library topology, frontend structure, deployment scripts, regression suites, and Windows restart readiness.

---

## 1. Executive Summary

Phase 4 transitions the institutional Calibre prototype from a static developer-configured setup into an autonomous, self-configurable institutional product. This audit evaluates the current architectural state, pinpoints hardcoded dependencies, analyzes session and credential retention risks, classifies system vs. administrator-editable settings, and defines the structural requirements for the Configuration Manager, Setup Wizard, and Administration interface.

### Audit Verdict:
- **Baseline Foundation:** Robust. 33/33 automated tests passing. Anti-caching, rate limiting, path traversal defenses, CSRF validation, and Calibre UI injection verified.
- **Key Gaps Identified:**
  1. Configuration is currently split across a static JSON file (`gateway_config.json`), hardcoded in-memory dictionaries (`USER_ROLES` in `gateway_server.py`), and static HTML template strings.
  2. First-time setup mechanism is absent; initial deployment assumes developer manual setup of libraries and user databases.
  3. Administrative management interface is missing; user creation, password changes, and library connections require terminal CLI commands.
  4. In-memory session store (`SESSIONS` dict) and plaintext Base64 credential retention in process RAM represent scalability and process-isolation bottlenecks for future multi-process or Windows Service architectures.

---

## 2. Inventory of Current Hardcoded Configuration & Gaps

### 2.1 File-by-File Hardcoding Assessment

| Component | Current Implementation | Hardcoded Values / Architectural Limitation | Remediation in Phase 4 |
| :--- | :--- | :--- | :--- |
| `gateway_server.py` | `CONFIG_FILE = ...gateway_config.json` | Reads fixed JSON file; defaults fallback to hardcoded constants. | Replace with dynamic `ConfigManager` backed by SQLite. |
| `gateway_server.py` | `USER_ROLES = {...}` | Fixed dictionary mapping `student1`, `faculty1`, `librarian1` to display names and roles. | Dynamic role mapping stored in institutional configuration database. |
| `gateway_server.py` | `build_injected_institutional_ui` | Hardcoded HTML strings for seal ("AIT"), title ("Aethelgard Institute of Technology"), sub-brand. | Dynamic templating driven by `ConfigManager` institutional settings. |
| `index.html` | Static Landing Page | Hardcoded institution title, seal badge ("AIT"), footer metadata, and port notices. | Server-side template placeholder replacement driven by `ConfigManager`. |
| `server-users.sqlite` | Calibre User DB | Populated via script; no graphical user management interface. | Wrap official Calibre user CLI (`calibre-server --manage-users`) in Admin GUI. |
| `portal.js` | Client Controller | Hardcoded endpoint paths and static alert text. | Remains modular; consumes dynamic status and config APIs. |

---

## 3. Configuration Classification: Admin-Editable vs. System-Protected

To maintain security, stability, and institutional policy compliance, settings must be strictly partitioned into two categories:

```
+-----------------------------------------------------------------------------------+
|                           CONFIGURATION ARCHITECTURE                              |
+-----------------------------------------------------------------------------------+
|  ADMIN-EDITABLE SETTINGS (Via Web GUI)    |  SYSTEM-PROTECTED SETTINGS (Engine Level) |
+-------------------------------------------+---------------------------------------+
|  - Institution Name & Short Name (Seal)   |  - Calibre Core Binaries Path         |
|  - Library Display Title & Welcome Text   |  - Gateway Loopback Listen Interface   |
|  - Institutional Logo (Secure Upload)     |  - Upstream Calibre Port (8088)       |
|  - Contact Email & Department Phone       |  - Session Cookie Security Flags      |
|  - Connected Calibre Libraries (Add/Paths)|  - Rate Limiter Thresholds & Windows  |
|  - Default Active Library                 |  - CSRF & Path Traversal Boundaries   |
|  - Patron Role Mappings & Display Names   |  - SQLite Database Encryption/Salt    |
|  - Library Access Policies (Public/Restr) |  - Windows Service Execution Account  |
+-------------------------------------------+---------------------------------------+
```

### 3.1 Administrator-Editable Settings (Mutable via Admin UI)
1. **Institution Identity:** Full name, abbreviation/seal text, primary/accent colors, uploaded logo image.
2. **Library Configuration:** Connected Calibre library folder paths, friendly display names, active/inactive toggles, default library selection.
3. **Institutional User Metadata:** Mapping Calibre user accounts to institutional display names, academic departments, and roles (`Administrator`, `Faculty`, `Student`, `Staff`).
4. **Library Access Restrictions:** Per-library visibility rules and restriction policies.

### 3.2 System-Protected Settings (Immutable via Web UI)
1. **Calibre Binary Paths:** Path to `calibredb.exe` and `calibre-server.exe` (validated from environment / registry).
2. **Loopback Backend Port (8088):** Calibre server must remain bound strictly to `127.0.0.1` and never exposed directly to the LAN.
3. **Session Security Directives:** `HttpOnly`, `SameSite=Lax`, cookie timeout defaults, sliding-window rate limit thresholds.
4. **Data Isolation Boundaries:** Prevention of file system navigation outside authorized institutional directories.

---

## 4. Evaluation of In-Memory Sessions & Basic Auth Credential Retention

### 4.1 Current Architecture & Identified Risks
- **Mechanism:** In Phase 1–3, `gateway_server.py` creates a unique cryptographic session token (`secrets.token_urlsafe(32)`) upon login. In process memory (`SESSIONS = {}`), it stores:
  ```python
  SESSIONS[token] = {
      "username": username,
      "role": role,
      "displayName": displayName,
      "basic_auth": b64_auth,  # base64(username:password)
      "expires_at": time.time() + SESSION_TIMEOUT
  }
  ```
  On every proxied request to `/calibre/*` or `/api/catalog`, the gateway injects `Authorization: Basic {session['basic_auth']}` into the upstream request header to satisfy Calibre's per-request HTTP Basic authentication.

### 4.2 Architectural Risks for Multi-Process & Windows Service Deployment
1. **Multi-Worker Process Isolation:** If the gateway runs under a multi-process WSGI server (e.g. multiple Python worker processes behind IIS or Windows Service supervisor), requests routed to worker B would fail if worker A holds the in-memory session.
2. **Gateway Restart Session Loss:** Restarting `gateway_server.py` wipes all active patron sessions, forcing everyone to re-authenticate.
3. **Plaintext Memory Exposure:** Storing cleartext `basic_auth` strings in RAM exposes credentials to process memory inspections or core dumps.

### 4.3 Phase 4 Architectural Recommendations
1. **Short-Term (Phase 4):**
   - Retain thread-safe in-memory session storage for development simplicity and speed, but decouple session state into a dedicated session manager interface.
   - Implement explicit memory zeroing/purging upon logout or timeout.
   - Store session records optionally in the local SQLite database (`inst_sessions` table) to persist sessions across gateway restarts without patron disruption.
2. **Medium-Term (Packaging/Production):**
   - Support DPAPI (Data Protection API) encryption for any retained credentials on Windows.
   - Explore Calibre server token/cookie authentication plugin to eliminate Basic Auth retention entirely.

---

## 5. First-Time Setup Wizard & Administrative Readiness

### 5.1 First-Time Setup Detection State Machine
```
                       +-------------------+
                       | System Startup    |
                       +-------------------+
                                 |
                                 v
                     [ Check System Config ]
                                 |
                 +---------------+---------------+
                 |                               |
       (setup_completed == 0)         (setup_completed == 1)
                 |                               |
                 v                               v
         [ Redirect /setup ]            [ Serve Portal / ]
                 |                               |
        +--------+--------+              +-------+-------+
        | Step 1: Env     |              | Patron Login  |
        | Step 2: Org     |              | Catalog Read  |
        | Step 3: Admin   |              | Admin Portal  |
        | Step 4: Library |              +---------------+
        | Step 5: Save    |
        +--------+--------+
                 |
                 v
      (Mark Completed = 1)
```

### 5.2 Calibre Official User Management Integration
Rather than executing raw SQL mutations against `server-users.sqlite` (which risks schema drift, hash algorithm mismatches, and lock collisions), the Administration interface must invoke official Calibre CLI commands:
- **List Users:** `calibre-server.exe --manage-users --userdb=<path> -- list`
- **Add User:** `calibre-server.exe --manage-users --userdb=<path> -- add <user> <pass> [--readonly]`
- **Change Password:** `calibre-server.exe --manage-users --userdb=<path> -- chpass <user> <pass>`
- **Set Readonly:** `calibre-server.exe --manage-users --userdb=<path> -- readonly <user> set|reset`
- **Delete User:** `calibre-server.exe --manage-users --userdb=<path> -- remove <user>`

Institutional user metadata (full name, department, role) will be managed in the institutional SQLite database and joined with Calibre's user registry at runtime.

---

## 6. Audit Conclusion & Phase 4 Roadmap

The gateway architecture is verified, stable, and ready for configuration management. In Task B, we implement `config_manager.py` backed by SQLite; in Task C, we construct the First-Time Setup Wizard; in Task D, we deploy the Institutional Administration Suite; in Task E, we bind all runtime templates dynamically to `config_manager.py`; and in Task F/G, we execute full acceptance and regression testing.
