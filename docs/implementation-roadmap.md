# Phased Implementation Roadmap
**Project:** Calibre Institutional Customization  
**Phase:** Phase 0 — Roadmap & Milestone Planning  
**Execution Horizon:** Phases 1 through 5  

---

## 1. Project Overview & Milestone Summary

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Phase 1    │────>│   Phase 2    │────>│   Phase 3    │────>│   Phase 4    │────>│   Phase 5    │
│  Dev Env &   │     │Institutional │     │Content Server│     │LAN Access,   │     │Desktop Brand │
│ Source Baseline│   │Landing Page  │     │ Integration  │     │HTTPS & Testing│    │  & Installer │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
  [COMPLETED]            [MVP Core]           [MVP Core]           [MVP Core]          [Future Opt.]
```

| Phase | Milestone Title | Primary Deliverable | Timeline | Target Scope |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 0/1** | Source Verification & Baseline Setup | Source clone, architecture discovery, verified audit | Week 1 | Completed |
| **Phase 2** | Institutional Landing Page & Auth | Branded web frontend, user registration & login | Weeks 2–3 | **Essential MVP** |
| **Phase 3** | Content Server Gateway Integration | Reverse proxy routing (`/calibre/`), session bridge | Weeks 3–4 | **Essential MVP** |
| **Phase 4** | LAN Deployment, TLS & End-to-End Testing | HTTPS termination, loopback binding, multi-device test | Weeks 4–5 | **Essential MVP** |
| **Phase 5** | Desktop Customization & Packaging | Inno Setup branded distribution, desktop shortcuts | Future Phase | Optional Polish |

---

## 2. Phase-by-Phase Task Breakdown

### Phase 1: Local Development Environment & Baseline Verification (Completed)
- **Objective:** Establish isolated workspace and verify environment without touching production.
- **Tasks:**
  - Audit running services, ports (8080, 80, 3306), and installed Calibre version (9.17.0).
  - Create workspace directory structure in `C:\dev\calibre-institutional\`.
  - Clone official Calibre source code repository (`git clone --depth 1`).
  - Verify version alignment and confirm Windows development runtime model (`CALIBRE_DEVELOP_FROM`).
  - Document complete architecture and security boundaries.

### Phase 2: Institutional Landing Page & Authentication Architecture (Essential MVP)
- **Objective:** Build the public-facing branded portal and user credential database.
- **Tasks:**
  - Design responsive, modern HTML5/CSS3 landing page showcasing institutional identity, digital library catalog search, and news.
  - Implement patron authentication system (Sign In, Password Reset, Profile Management).
  - Configure user database backend with secure password hashing (Argon2id/Bcrypt).
  - Implement role-based authorization (Students, Faculty, Guest, Administrators).
  - Deliverables: Frontend templates, authentication controller, and session management module in `customization/frontend/` and `customization/backend/`.

### Phase 3: Integration with Calibre Content Server (Essential MVP)
- **Objective:** Bridge the institutional landing page with Calibre's book browsing and reading capabilities.
- **Tasks:**
  - Configure Calibre Content Server with `--url-prefix /calibre` and `--auth-mode basic`.
  - Configure Apache / Reverse Proxy to route `/calibre/` requests to upstream `127.0.0.1:8080`.
  - Implement session bridge: Gateway validates institutional login, then transparently authorizes requests to Calibre.
  - Test seamless transition: Patron logs in at landing page -> browses catalog -> launches in-browser eBook reader (`read_book.pyj`) without secondary authentication prompts.
  - Deliverables: Reverse proxy virtual host configuration and integration middleware in `customization/configuration/`.

### Phase 4: LAN Accessibility, HTTPS, Hardening & End-to-End Testing (Essential MVP)
- **Objective:** Enable secure campus Wi-Fi access, harden security, and perform multi-device QA.
- **Tasks:**
  - Rebind Calibre Content Server strictly to `127.0.0.1` (`--listen-on 127.0.0.1`).
  - Configure TLS / HTTPS certificate on the gateway for LAN IP (`https://192.168.0.107/`).
  - Conduct end-to-end testing across desktop Chrome, Edge, Firefox, Android, and iOS mobile devices.
  - Verify book search, streaming, bookmarking, and offline service worker compatibility.
  - Deliverables: Production deployment scripts, security hardening checklist, and validation report.

### Phase 5: Institutional Desktop Branding & Windows Installer (Optional Future Scope)
- **Objective:** Package a customized desktop installation for collection managers.
- **Tasks:**
  - Create institutional desktop icon assets and splash screen branding.
  - Build an Inno Setup installer script that:
    - Bundles the official Calibre 9.x binary package.
    - Automatically creates institutional desktop shortcuts (`Institutional Library Manager`).
    - Configures default server launch scripts and institutional registry entries.
  - Avoids the extreme maintenance overhead of maintaining a source-level C++ fork.
  - Deliverables: Inno Setup build script (`setup/institutional-installer.iss`) in `customization/branding/`.

---

## 3. Definition of MVP Success

The Minimum Viable Product (MVP) is successful when:
1. Calibre Desktop runs uninterrupted on the host machine, and librarians manage books as normal.
2. Any device connecting to the campus Wi-Fi can navigate to `https://192.168.0.107/` and see the branded landing page.
3. Unauthenticated users are required to sign in with their individual institutional account.
4. Authenticated users can search, browse, and read books in their browser without seeing raw HTTP Digest prompts.
5. Direct external access to port 8080 is blocked by loopback binding.
