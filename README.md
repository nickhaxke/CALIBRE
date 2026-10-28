# Calibre Institutional Digital Library Customization

## Current source-based demonstration — 28 October 2026

The current demo customizes Calibre's Content Server and Qt desktop on the
`institutional/friday-demo` source branch. It uses the installed Calibre 9.17.0
native runtime with `CALIBRE_DEVELOP_FROM`; no replacement library engine is used.

```powershell
cd C:\dev\calibre-institutional
.\scripts\start-demo.ps1 -Desktop
```

Open <http://127.0.0.1:8085/>. Generated reader/admin credentials are in the
ignored `.demo/credentials.json`. All demo books, databases, logs and the desktop
profile are isolated under `.demo/`. Stop the web processes with
`.\scripts\stop-demo.ps1`; the desktop remains open.

See [the demonstration guide](docs/friday-demo.md) for evidence, verification,
source paths and limitations. The installer in `dist/` predates this sprint and
must not be used to deliver the new source changes.

The Phase 0 notes below are historical. Use the current launcher and isolated
tests instead of running the legacy development scripts or the whole legacy
test directory against existing data.

---

**Phase 0:** Development Environment Setup, Source Acquisition & Architecture Discovery  
**Target Platform:** Windows x86_64  
**Base Application:** Calibre 9.17.0  

---

## 1. Project Background & Architecture

This project establishes a customized institutional digital library for campus LAN/Wi-Fi users while preserving Calibre Desktop as the daily cataloguing application for collection managers.

### Core Architecture (Option A: Institutional Gateway)
```
[ Campus LAN / Wi-Fi Patrons ]
              │ (HTTP/HTTPS)
              ▼
[ Institutional Gateway (Port 80/443) ]
  ├── Branded Landing Page & Search
  ├── Patron Account Authentication
  └── Secure Reverse Proxy Router (/calibre/)
              │ (Authenticated Loopback)
              ▼
[ Calibre Content Server (127.0.0.1:8080) ]
  ├── In-Browser eBook Reader (RapydScript SPA)
  └── Book Metadata & Streaming Engine
              ▲
              │ (Read-Only)
[ Calibre Library (metadata.db) ] ◄── [ Calibre Desktop (Librarians) ]
```

---

## 2. Workspace Directory Layout

```
C:\dev\calibre-institutional\
├── upstream/
│   └── calibre/              # Official Calibre 9.17.0 reference source code
├── customization/
│   ├── frontend/             # Branded landing page templates & assets
│   ├── backend/              # Institutional authentication & session gateway
│   ├── branding/             # Custom logos, icons, and theme definitions
│   └── configuration/        # Reverse proxy and server configuration profiles
├── docs/
│   ├── environment-audit.md  # Host tools, ports, and pre-flight inspection findings
│   ├── source-code-map.md    # Source code analysis, entry points, and APIs
│   ├── architecture-analysis.md # Comparative evaluation of Options A, B, and C
│   ├── security-assessment.md   # LAN threat model and required security controls
│   └── implementation-roadmap.md # Phased implementation plan (Phases 1–5)
├── scripts/
│   ├── verify-environment.ps1   # PowerShell non-destructive environment verification
│   ├── inspect-source.py        # Python CLI inspection utility
│   └── run-dev-server.ps1       # Safe test server runner on isolated port
├── tests/
│   └── test_environment.py     # Automated environment verification test suite
└── README.md
```

---

## 3. Quickstart & Safe Diagnostic Commands

### 3.1 Verify Development Environment
Run the automated PowerShell verification script:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\dev\calibre-institutional\scripts\verify-environment.ps1
```

### 3.2 Inspect Source Code Structure
Query Calibre's source code components using the inspection utility:
```bash
python C:\dev\calibre-institutional\scripts\inspect-source.py
```

### 3.3 Run Automated Sanity Tests
Execute the automated test suite:
```bash
python -m unittest discover -s C:\dev\calibre-institutional\tests
```

---

## 4. Safety & Operational Constraints

1. **Production Preservation:** Never modify `C:\Program Files\Calibre2` or `C:\Users\USER\Calibre Library\metadata.db`.
2. **Process Integrity:** Never terminate or restart the running production Calibre process (PID 23128) on port 8080.
3. **Port Isolation:** Development test servers must use an alternate port (e.g., `8088`).
