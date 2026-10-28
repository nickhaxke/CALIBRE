# Institutional Calibre — Phase 5: Release & Deployment Guide

## 1. Executive Summary

This document defines the deployment architecture, installation requirements, first-time setup procedure, and production LAN security guidelines for the **Calibre Institutional MVP (Version 1.0.0)**.

The deployment package is delivered as a standalone Windows installer created with Inno Setup 6, bundling a self-contained runtime for the Institutional Gateway Server and integrating directly with an existing official Calibre installation without modifying original binaries or existing Calibre book collections.

---

## 2. Deliverable & Integrity Verification

- **Installer File Name:** `CalibreInstitutional-Setup.exe`
- **Installer Location:** `C:\dev\calibre-institutional\dist\CalibreInstitutional-Setup.exe`
- **File Size:** 10071036 bytes (~9.6 MB)
- **SHA-256 Checksum:** `EBDC5F687194B81B85A392D21D213B4E0A84DBFD766945057E858E2D2581B1E5`
- **Compiler:** Inno Setup 6.4.1 (ISCC)
- **Architecture:** x64 (Windows 64-bit)

To verify package integrity on a target machine prior to execution:
```powershell
Get-FileHash -Path "CalibreInstitutional-Setup.exe" -Algorithm SHA256
# Expected output: EBDC5F687194B81B85A392D21D213B4E0A84DBFD766945057E858E2D2581B1E5
```

---

## 3. System Requirements & Compatibility

### Supported Operating Systems
- Windows 11 (64-bit) — Tested and verified
- Windows 10 (64-bit, Version 1809 or later)
- Windows Server 2016, 2019, 2022, 2025

### Calibre Compatibility
- **Pre-installed Official Calibre Desktop:** 7.x through 9.x (64-bit)
- **Default Installation Location:** `C:\Program Files\Calibre2` (auto-detected via Windows Registry or standard program paths)
- **Compatibility Guarantee:** The installer detects `calibre-server.exe` and `calibre.exe`. It strictly **refuses** to overwrite, modify, or bundle an unverified version of Calibre.

### Hardware Prerequisites
- **RAM:** Minimum 2 GB (4 GB recommended for large libraries >10,000 volumes)
- **Disk Space:** 50 MB for Institutional Gateway application and runtime (plus required storage for institutional book collections)
- **Network:** Static LAN IP address or institutional DNS hostname for server host

---

## 4. Legal Compliance & Licensing Architecture

Calibre Institutional complies with the **GNU General Public License v3 (GPLv3)** under which Calibre is distributed:

1. **Strict IPC Process Boundary:** Calibre Institutional does not link, embed, or statically combine with Calibre code. The Institutional Gateway interacts exclusively with Calibre as a separate subprocess over loopback HTTP and local CLI IPC.
2. **Untouched Binaries:** Calibre Desktop and `calibre-server.exe` remain completely original and unmodified.
3. **Preserved License Notices:** 
   - Full GPLv3 text is installed to `{app}\licenses\CALIBRE_GPL_v3.txt`.
   - Calibre copyright notices are installed to `{app}\licenses\CALIBRE_COPYRIGHT.txt`.
   - Calibre Institutional MIT/custom license is provided in `{app}\licenses\LICENSE.txt`.

---

## 5. Installation Procedure

### Standard Interactive Installation
1. Log in to the Windows server host as an Administrator.
2. Double-click `CalibreInstitutional-Setup.exe`.
3. If an existing Calibre installation is present in `C:\Program Files\Calibre2`, the installer automatically detects it and proceeds. If not detected, the installer prompts the user to select the Calibre installation path or install Calibre first.
4. Choose the installation directory (default: `C:\Program Files\Calibre Institutional` or `%LOCALAPPDATA%\Programs\Calibre Institutional`).
5. Choose whether to install the automatic Windows Startup Task / Service.
6. Click **Install**.
7. Upon completion, select **Launch Institutional Setup Wizard** (opens `http://127.0.0.1:8085/setup`).

### Unattended / Silent Installation
For network administrators provisioning via automation (Active Directory GPO, MDM, or PowerShell scripts):
```cmd
CalibreInstitutional-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="C:\Program Files\Calibre Institutional"
```

---

## 6. Tested First-Time Setup Instructions

The setup wizard is only accessible from local loopback (`127.0.0.1` or `::1`) on the server host to prevent unauthorized bootstrapping over the LAN.

### Step 1: Access the Wizard
On the host machine, open a browser and navigate to:
```
http://127.0.0.1:8085/setup
```

### Step 2: Configure Institution Profile
- **Institution Name:** Enter the official legal or operating name (e.g., `Metropolitan Institute of Technology`).
- **Institution Abbreviation:** Short display code (e.g., `MIT`).
- **Institutional Logo:** Upload a PNG, JPG, or SVG logo (or accept the default institutional crest).

### Step 3: Register Administrator Account
- **Admin Username:** Primary administrative username (e.g., `admin`).
- **Admin Password:** Strong password (minimum 8 characters, checked against strength policies).
- **Admin Email:** Institutional contact email.

### Step 4: Mount Calibre Library
- Select or enter the absolute path to the existing Calibre library containing `metadata.db` (e.g., `C:\Users\USER\Calibre Library`).
- The wizard validates that `metadata.db` exists in the folder before proceeding.

### Step 5: Finalize Setup
- Click **Complete Setup**.
- The backend initializes the encrypted user store, launches `calibre-server.exe` on loopback port `8088`, registers the admin account, marks setup as completed, and redirects to the branded institutional portal.

---

## 7. Windows Service & Automatic Startup

The Institutional Gateway is engineered to run as an independent background service:

1. **Independent of User Sessions:** Runs regardless of whether a Windows user is logged into the console.
2. **Independent of Calibre Desktop:** Calibre Desktop can be opened, closed, or used to edit metadata at any time. The background supervisor handles book reading requests continuously.
3. **Scheduled Task / Service Manager:**
   - Management script: `scripts\service_manager.py`
   - Convenient batch controls provided in installation root:
     - `start-service.bat`
     - `stop-service.bat`
     - `install-service.bat`
     - `uninstall-service.bat`
   - Configures a high-priority Windows Scheduled Task (`CalibreInstitutionalGateway`) set to start `AtStartup` under the `SYSTEM` or service account with automatic restart on failure.

---

## 8. LAN Deployment & Production Security (HTTPS / DNS)

### Security Warning: Insecure HTTP Prohibition
> [!CAUTION]
> In accordance with release-blocking security requirements, user credentials and session tokens **MUST NEVER** be transmitted in plaintext across the local area network. The Institutional Gateway listens on loopback (`127.0.0.1:8085`) and must be fronted by a TLS-terminating reverse proxy.

### Network Architecture Diagram
```
[ Institutional LAN / Wi-Fi Users ]
               │
               │ HTTPS (Port 443) — TLS 1.3
               ▼
┌────────────────────────────────────────┐
│  Reverse Proxy (Caddy / Nginx / IIS)   │
│  Hostname: library.institution.edu     │
│  Valid Institutional or ACME TLS Cert  │
└──────────────────┬─────────────────────┘
                   │
                   │ Loopback HTTP (127.0.0.1:8085)
                   ▼
┌────────────────────────────────────────┐
│    Calibre Institutional Gateway       │
│  - Session Auth (HttpOnly Cookies)     │
│  - Branded Landing Page & Admin UI     │
│  - Multi-Library Dynamic Proxy         │
└──────────────────┬─────────────────────┘
                   │
                   │ Loopback Basic Auth (127.0.0.1:8088)
                   ▼
┌────────────────────────────────────────┐
│      Calibre Content Server            │
│  (calibre-server.exe subprocess)       │
└──────────────────┬─────────────────────┘
                   │
                   ▼
       [ Calibre Library Storage ]
```

### Recommended Reverse Proxy: Caddy Server (Automated TLS)
Create `Caddyfile` on the host:
```caddy
library.institution.edu {
    reverse_proxy 127.0.0.1:8085
    
    # Security Headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
}
```

### Alternative Reverse Proxy: Nginx on Windows
```nginx
server {
    listen 443 ssl http2;
    server_name library.institution.edu;

    ssl_certificate     C:/ssl/cert.pem;
    ssl_certificate_key C:/ssl/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8085;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

### DNS & Firewall Configuration
1. **Institutional DNS:** Point `library.institution.edu` to the server's static LAN IP address (e.g., `192.168.1.50`).
2. **Windows Firewall Rule:**
   ```powershell
   New-NetFirewallRule -DisplayName "Institutional Library HTTPS" -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow
   ```
   Do **NOT** open port 8085 or 8088 directly to the LAN.

---

## 9. Data Preservation & Lifecycle Policy

The installer and uninstaller are engineered to guarantee zero data loss:

1. **User Databases Preserved:** The configuration databases (`config.sqlite3`, `calibre_users.sqlite3`) reside in `%LOCALAPPDATA%\CalibreInstitutional\config` (or custom data directory). The Inno Setup uninstaller explicitly **retains** all database files and uploaded institution logos.
2. **Book Libraries Preserved:** The original Calibre library folder and `metadata.db` are never altered or deleted during installation, reconfiguration, upgrade, or uninstallation.
3. **Seamless Upgrades:** Running a new installer version upgrades application binaries while seamlessly maintaining existing user accounts, libraries, and branding.
