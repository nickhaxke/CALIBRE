# Architecture Analysis & Comparative Evaluation
**Project:** Calibre Institutional Customization  
**Phase:** Phase 0 — Recommended Solution Design  
**Author:** Principal Software Architect, Python Engineer & Security Engineer  
**Date:** 2026-10-26  

---

## 1. Context & Objectives

The institutional digital library requires:
1. Retaining Calibre Desktop for collection administrators without disrupting book-cataloguing workflows.
2. Delivering a branded, modern institutional landing page for campus LAN/Wi-Fi users.
3. Requiring individual user authentication before accessing digital assets.
4. Enabling authorized patrons to browse, search, and read library books across desktop and mobile browsers.
5. Operating on Windows with zero downtime, high upgrade maintainability, and clean coexistence with existing WAMP/Apache services.

---

## 2. Deep Dive: Authentication Challenge Mechanics

A central architectural question is why a custom HTML login form cannot directly replace Calibre's native authentication challenge without an intermediary integration layer.

### 2.1 The RFC 2617 HTTP Digest Challenge
Calibre's Content Server enforces authentication using standard HTTP Digest Authentication:
```
Client Browser                  Calibre Content Server
     │                                     │
     ├──────── GET /interface-data/init ──>│
     │                                     │
     │<─── 401 Unauthorized ───────────────┤
     │     WWW-Authenticate: Digest        │
     │     realm="calibre", nonce="..."    │
     │                                     │
```
When a web browser encounters an HTTP 401 response with a `WWW-Authenticate` header, the browser's native networking engine intercepts the response:
- The browser halts execution of page JavaScript.
- The browser renders a browser-native modal credential dialog.
- This modal dialog is controlled exclusively by the operating system / browser UI and **cannot be styled, branded, or populated by HTML/CSS**.
- Furthermore, modern browsers (Chrome, Edge, Safari) do not provide a JavaScript API to dismiss, intercept, or pre-emptively supply HTTP Digest credentials to this challenge without triggering native prompt behavior unless valid `Authorization` headers are sent with the initial request.

### 2.2 The Session Cookie vs. HTTP Auth Mismatch
- Modern web applications authenticate users via HTML `<form>` submissions that exchange credentials for an encrypted session cookie (`Set-Cookie: session_id=...`).
- Calibre's Content Server API endpoints do **not** check custom session cookies (except for a temporary workaround cookie for Android file downloads).
- Therefore, simply serving a custom HTML login page on port 8080 does not allow users to access Calibre's API unless either:
  1. Calibre's backend authentication logic (`src/calibre/srv/auth.py`) is rewritten to support cookie-based sessions, or
  2. A secure reverse proxy / gateway intercepts user requests, validates institutional session cookies, and injects the required `Authorization` credentials upstream to Calibre.

---

## 3. Detailed Comparative Evaluation of Options

We evaluated three potential architectural strategies across eight mission-critical engineering criteria:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Option A: Institutional Gateway & Reverse Proxy (Recommended)          │
│ ┌──────────────────────┐    ┌─────────────────┐    ┌─────────────────┐ │
│ │ Campus LAN / Wi-Fi   │───>│ Gateway Proxy   │───>│ Calibre Server  │ │
│ │ Patrons (HTML Portal)│    │ (Auth & Branding│    │ (127.0.0.1:8080)│ │
│ └──────────────────────┘    └─────────────────┘    └─────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────┐
│ Option B: Direct Content Server Modification (RapydScript Fork)        │
│ ┌──────────────────────┐    ┌────────────────────────────────────────┐ │
│ │ Campus LAN / Wi-Fi   │───>│ Patched Calibre Content Server         │ │
│ │ Patrons              │    │ (Modified auth.py & src/pyj/ templates)│ │
│ └──────────────────────┘    └────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────┐
│ Option C: Full Calibre Source Fork & Custom Windows Packaging          │
│ ┌──────────────────────┐    ┌────────────────────────────────────────┐ │
│ │ Modified Calibre     │    │ Linux CI/CD QEMU Build Cluster         │ │
│ │ Windows Distribution │<───│ (bypy, custom PyQt6, custom installer) │ │
│ └──────────────────────┘    └────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Evaluation Matrix

| Evaluation Criteria | Option A: Unmodified Calibre + Institutional Gateway | Option B: Custom Content Server Frontend | Option C: Full Calibre Source Fork & Installer |
| :--- | :--- | :--- | :--- |
| **1. Technical Feasibility** | **High:** Uses supported reverse proxy (`--url-prefix`, `--auth-mode basic`) and standard web technologies. | **Medium:** Requires compiling RapydScript (`.pyj`) and patching Python HTTP server. | **Low:** Building Windows installers requires Linux QEMU virtual machines (`bypy`). |
| **2. Authentication Security** | **Exceptional:** Role-based access control, modern password hashing (Argon2/Bcrypt), MFA readiness, TLS termination. | **Poor:** Bound to HTTP Digest (MD5) or Basic auth; session hijacking vulnerability on LAN. | **Medium:** Capable of custom auth but requires maintaining complex native C/Python patches. |
| **3. User Experience** | **Premium:** Responsive, beautifully styled institutional landing page, search, and reading interface. | **Basic:** Constrained to Calibre's built-in UI layout and browser-native login prompts. | **Custom:** Tailored desktop and web UI, but high development overhead. |
| **4. Maintenance Complexity** | **Low:** Clean separation of concerns. Gateway and Calibre are decoupled services. | **High:** Upstream updates frequently break custom RapydScript patches and templates. | **Extreme:** Requires tracking upstream Calibre commits, rebasing patches, and managing native builds. |
| **5. Upgrade Compatibility** | **Zero Friction:** Calibre can be upgraded to any new official release without touching gateway code. | **Fragile:** Every upstream update overwrites `resources/content-server` and requires re-compilation. | **Prohibitive:** Upgrades require full re-compilation of C/C++ libraries and Qt bindings. |
| **6. Development Effort** | **Minimal:** 2–3 weeks to functional production MVP. | **Moderate:** 4–6 weeks including RapydScript toolchain setup. | **Massive:** 3–6 months for CI/CD pipeline, build infrastructure, and testing. |
| **7. Deployment Requirements** | Standard Windows deployment; leverages existing WAMP Apache or lightweight reverse proxy. | Direct deployment to Calibre installation folder; permissions and service restart risks. | Requires dedicated Linux build server, Windows code-signing certificates, and packaging pipeline. |
| **8. Long-Term Sustainability** | **Optimal:** Independent evolution of institutional features without upstream lock-in. | **At Risk:** High likelihood of abandonment due to maintenance friction. | **High Risk:** High ongoing maintenance burden for a single institution. |

---

## 4. Architectural Recommendation: Option A

### 4.1 Recommended Architecture Description
We recommend **Option A: Unmodified Calibre Backend with Secure Institutional Gateway & Branded Landing Page**.

In this architecture:
1. **Calibre Desktop & Embedded Content Server remain 100% stock:**
   - Librarians continue using Calibre Desktop as they do today.
   - Content Server runs locally on loopback (`127.0.0.1:8080`) with `--url-prefix /calibre` and `--auth-mode basic`.
   - The production Calibre library (`C:\Users\USER\Calibre Library`) and `metadata.db` remain completely unmodified.
2. **Institutional Gateway Layer (Port 80 / 443):**
   - Implemented via Apache (already active via WAMP) or a dedicated lightweight reverse proxy service.
   - Serves the **Branded Institutional Landing Page** to LAN/Wi-Fi users (`http://192.168.0.107/`).
   - Manages individual user registration, institutional credentials, login sessions, and permission checks.
   - Authenticated patrons access book browsing, search, and in-browser reading through a secure reverse proxy route (`/calibre/`), where the gateway seamlessly passes authorized requests upstream.
3. **Phase 5 Desktop Enhancement (Non-Forking):**
   - For future desktop branding, rather than maintaining a fragile source fork, we recommend an **Inno Setup packaging wrapper** that distributes the official Calibre release pre-configured with institutional desktop shortcuts, brand icons, and default server parameters.

### 4.2 Why This is the Superior Solution
- **Reliability:** Leaves the core Calibre engine untouched, guaranteeing zero database corruption or library degradation.
- **Enterprise Security:** Binds Calibre to loopback (`127.0.0.1`), ensuring unauthenticated LAN users cannot bypass institutional controls by hitting port 8080 directly.
- **Seamless Upgrades:** The client can update Calibre whenever new official versions are released without breaking the institutional portal.
