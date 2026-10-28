# Environment & Infrastructure Audit Report
**Project:** Calibre Institutional Customization  
**Phase:** Phase 0 — Development Environment Setup, Source Acquisition & Architecture Discovery  
**Audit Timestamp:** 2026-10-26T19:55:00+03:00  
**Host Architecture:** Windows x86_64  
**Audit Status:** Complete & Verified  

---

## 1. Executive Summary

This pre-flight audit establishes the empirical baseline for the institutional digital library customization project. The inspection was conducted using strictly non-destructive, read-only diagnostic procedures. All existing applications, including the client's active Calibre Desktop instance, the embedded Content Server on port 8080, and the WAMP web stack, were kept completely operational without interruption.

---

## 2. Calibre Production Installation

| Diagnostic Check | Verification Method | Discovered Value | Architecture Significance |
| :--- | :--- | :--- | :--- |
| **Installed Binary Version** | `calibredb.exe --version`, `calibre-server.exe --version` | **9.17.0** | Matches the latest official upstream release |
| **Installation Path** | Filesystem inspection | `C:\Program Files\Calibre2` | Strictly preserved; read-only |
| **Runtime Packaging** | Process tree & DLL analysis | Bundled Python 3.11 + PyQt6 | Standalone distribution with self-contained runtime |
| **Primary Executables** | Directory listing | `calibre.exe`, `calibre-server.exe`, `calibredb.exe`, `calibre-debug.exe`, `ebook-convert.exe` | Located in root directory of Calibre2 |
| **Subdirectory Structure** | Directory listing | `app/bin`, `app/plugins`, `app/resources`, `app/share`, `app/translations` | Complete pre-compiled C extensions and assets |

---

## 3. Host System Tools & Development Dependencies

| Tool / Environment | Invocation / Query | Detected Version / Status | Assessment |
| :--- | :--- | :--- | :--- |
| **Operating System** | PowerShell CIM | Windows 10/11 x64 (Build 19045+) | Standard enterprise workstation/server host |
| **System Python** | `python --version` | `Python 3.14.4` (64-bit) | Modern system interpreter on `C:\Python314` |
| **Calibre Internal Python** | `calibre-debug.exe` | Embedded Python 3.11 runtime | Native Calibre runtime with compiled C extensions |
| **Git** | `git --version` | `git version 2.56.0.windows.2` | Available in system PATH (`C:\Program Files\Git`) |
| **C/C++ Compiler (`cl.exe`)** | `Get-Command cl.exe` | Not in PATH | Not required for Python develop mode |
| **CMake** | `Get-Command cmake` | Not in PATH | Not required for Python develop mode |
| **Disk Space (C:)** | `Get-PSDrive C` | **46.7 GB Free** / 191.1 GB Used | Sufficient for repo, build cache & docs |
| **Workspace Permissions** | Directory creation test | Full read/write in `C:\dev\` | Safe outside Program Files |

### Official Windows Development Requirements Note
As documented in the official Calibre Developer Documentation ([develop.html](https://manual.calibre-ebook.com/develop.html)):
- Calibre on Windows does **not** require compiling C++ extensions from scratch for application logic development.
- Developers use the official binary installation as the native runtime engine and point the environment variable `CALIBRE_DEVELOP_FROM` to the checked-out source code directory (`C:\dev\calibre-institutional\upstream\calibre\src`).
- Attempting to execute Calibre directly with system Python (`python.exe -m calibre`) fails because Calibre depends on compiled C/C++ extensions (`apsw`, `sqlite_extension`, `speedup`, `unrar`, `podofo`, `pictureflow`, `pyqt6`) bundled inside `C:\Program Files\Calibre2\app\bin`.

---

## 4. Library & Configuration Discovery

| Target Component | Source Path / Key | Discovered Value | Integrity Status |
| :--- | :--- | :--- | :--- |
| **Active Library Directory** | `%APPDATA%\calibre\global.py.json` | `C:\Users\USER\Calibre Library` | Unmodified, active production data |
| **Metadata Database** | Library root folder | `metadata.db` | SQLite 3 database; read-only inspection |
| **Library Usage History** | `%APPDATA%\calibre\gui.json` | `{"C:/Users/USER/Calibre Library": 2}` | Active in GUI |
| **Server Configuration** | `%APPDATA%\calibre\server-config.txt` | `auth True` | Authentication actively enforced |
| **User Credential Store** | `%APPDATA%\calibre\server-users.sqlite` | 12,288 bytes SQLite database | Protected credential database |
| **Custom Templates** | `%APPDATA%\calibre\server-custom-list-template.json` | Configured | UI customizations |

---

## 5. Network, Process & Port Audit

| Port | Process Name | PID | Bind IP | Service / Application | Potential Conflicts |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **80** | `httpd.exe` | 7456 | `0.0.0.0` / `::` | Apache (WAMP) | Active web server; can act as reverse proxy |
| **443** | None | — | — | Available | Candidate for HTTPS termination |
| **3306** | `mysqld.exe` | 11736 | `::` | MySQL (WAMP) | Available for institutional user management |
| **8080** | `calibre.exe` | 23128 | `::` (Dual stack) | Calibre Embedded Content Server | Active; do not terminate or rebind |
| **LAN IPv4** | Wi-Fi Interface | — | `192.168.0.107` | Host LAN Address | Validated target for LAN users |

### Content Server Process Findings
- Process ID `23128` is `calibre.exe` (`C:\Program Files\Calibre2\calibre.exe`).
- The Content Server is **not** running as an independent headless Windows service (`calibre-server.exe`), but is running **embedded within the Calibre Desktop GUI process** via `calibre.srv.embedded:EmbeddedServer`.
- The server is listening on port `8080` on all network interfaces (`:: 8080`).

### Authentication Challenge Verification
- Direct HTTP GET `/` (`http://192.168.0.107:8080/`) returns HTTP 200 with the single-page application bootstrap HTML (`index-generated.html`, Content-Length ~4 MB).
- Direct HTTP GET to API endpoints (e.g. `/interface-data/init`, `/ajax/categories`) returns:
  ```http
  HTTP/1.1 401 Unauthorized
  WWW-Authenticate: Digest realm="calibre", nonce="...", algorithm="MD5", qop="auth"
  ```
- **Architectural implication:** Calibre Content Server uses **HTTP Digest Authentication** (`RFC 2617`). A standard HTML `<form>` submission cannot directly satisfy an HTTP 401 Digest challenge without either a reverse proxy/session bridge or an automated client-side digest response generator.

---

## 6. Coexistence Strategy & Recommendations

1. **WAMP Coexistence:**
   - Apache is currently on port 80; Calibre Content Server is on port 8080.
   - WAMP Apache can be configured with `mod_proxy`, `mod_proxy_http`, and `mod_ssl` to provide a branded reverse proxy on `http://192.168.0.107/library` or an HTTPS port (443).
2. **Port Isolation:**
   - Any secondary test server instances developed in Phase 1 must bind to an alternate port (e.g., `8088` or `8081`) to avoid port collisions with the running production Calibre server on `8080`.
3. **Library Safety:**
   - Development must point to an isolated test library directory (`C:\dev\calibre-institutional\tests\fixtures\test-library`), strictly avoiding any write access or lock conflicts with `C:\Users\USER\Calibre Library`.
