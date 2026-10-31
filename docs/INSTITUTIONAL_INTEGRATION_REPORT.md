# Calibre Institutional — Server & Portal Integration Report

**Project:** `C:\dev\calibre-institutional`  
**Distribution Target:** Windows x64 (`dist/Calibre-Institutional-Setup.exe`)  
**SHA-256:** `51B0374D337D54C20456463CD1ADEDB39188208B4D897A49F3617B132E97A2B3`  
**Installer Size:** 268,258,417 bytes (~255.8 MB)  
**Date:** October 29, 2026  

---

## Executive Summary

The project owner reported a confusing experience where clicking **Connect/share → Start Content Server** in the installed Calibre Desktop launched the native stock Calibre Content Server on port `8080` (displaying the stock dark interface) rather than the customized Institutional Gateway on port `8085` (cream/green branding), leaving the owner unable to access the institutional portal or find the administrative console.

We conducted an end-to-end diagnosis and executed full integration across the Calibre GUI, Connect/Share menu, toolbar, Institutional Server manager, and backend gateway. The two servers are now clearly disambiguated, desktop controls provide direct 1-click access to the Institutional Portal and Admin Console, and library synchronization between the desktop database and web catalogue is fully verified on the real installed runtime.

---

## 1. Root Cause Analysis

Calibre Institutional features a dual-server architecture:
1. **Native Calibre Content Server (`srv` engine):** Calibre's internal OPDS/web server running on port `8080`.
2. **Institutional Gateway (`gateway_server.py`):** The Python institutional web service running on port `8085` which exposes the institutional landing page, institutional search catalogue, role-based authentication, and admin console, proxying book data via a loopback Calibre backend server on port `8088`.

### Why the Owner Was Confused:
* **Missing Menu Integration:** The Calibre desktop **Connect/share** menu (`ShareConnMenu` in `upstream/calibre/src/calibre/gui2/actions/device.py`) hardcoded only the stock Calibre server actions (`_('Start Content server')` and `_('Visit Content server in browser')`). It had zero references to the Institutional Gateway on port `8085`.
* **Low Discoverability:** The Institutional Server controls were only accessible through an obscure text label in the bottom status bar and a tool action named `'Library Server'` (`lt.png`) that was not included in the default toolbar layout.
* **Missing Admin Console Links:** The `InstitutionalServerDialog` only had an "Open Library Website" button (`http://127.0.0.1:8085/`) and no direct link or button to access the Admin Console (`http://127.0.0.1:8085/admin`).
* **Stale Demo Database Reference:** The institutional configuration database (`institutional_config.sqlite`) previously had an old development fixture path (`C:\dev\calibre-institutional\.demo\library`) marked as default (`is_default=1`), rather than dynamically resolving the user's active Calibre Desktop library (`C:\Users\USER\Calibre Library`).

---

## 2. Institutional Server Manager Status & Architecture

The Institutional Server Manager (`upstream/calibre/src/calibre/gui2/institutional_server.py`) was already functional under the hood:
* It reads configuration from `%LOCALAPPDATA%\CalibreInstitutional\config\institutional_config.sqlite`.
* It spawns `gateway_server.py` on port `8085` with `--backend-port 8088` using the bundled Python runtime `calibre\app\bin\python.exe`.
* It supervises the background loopback Calibre backend process on port `8088`.
* It monitors PID health, port responsiveness, and logs to `%LOCALAPPDATA%\CalibreInstitutional\logs\gateway.log`.

**What Was Missing:** UI/UX visibility, menu prominence, admin links, and automatic active library synchronization.

---

## 3. Implementation & Code Changes

### A. Connect/Share Menu Disambiguation
**File:** `upstream/calibre/src/calibre/gui2/actions/device.py`
* Added Institutional Server actions to the top of the **Connect/share** menu:
  * `Institutional Server Controls...` (launches server management dialog)
  * `Open Institutional Library Website (Port 8085)` (opens landing page in browser)
  * `Open Institutional Admin Console (Port 8085)` (opens admin console in browser)
  * Followed by a separator line.
* Renamed stock actions to clearly disambiguate:
  * `Start Native Content server (Port 8080)`
  * `Visit Native Content server in browser (Port 8080)`
  * `Stop Native Content server (Port 8080)`

### B. Institutional Server Manager & Dialog Enhancement
**File:** `upstream/calibre/src/calibre/gui2/institutional_server.py`
* Added `open_admin_console(self)` method opening `{gateway_url}/admin`.
* Added `reload_backend(self)` method invoking the gateway `/api/admin/system/reload` API.
* Enhanced `InstitutionalServerDialog`:
  * Added `self.btn_admin = QPushButton("🛡 Open Admin Console")` alongside `self.btn_open`.
  * Synchronized button enabled/disabled states: both buttons activate whenever the server transitions to `RUNNING`.
* Automatic Library Synchronization (`sync_active_library`):
  * Inspects `gui.current_db.library_path`.
  * Normalizes path and writes to `institutional_config.sqlite`.
  * Clears any legacy fixture paths (`.demo` or `C:\dev`).
  * Sets the user's active Calibre library to `is_active=1` and `is_default=1`.

### C. Toolbar & Status Bar Discoverability
**Files:** 
* `upstream/calibre/src/calibre/gui2/actions/institutional_server.py`
* `upstream/calibre/src/calibre/gui2/__init__.py`
* Added `'Institutional Server'` to the default Calibre main toolbar layout (`action-layout-toolbar`) right next to `'Connect Share'`.
* Changed action name to `Institutional Portal` and icon to `network-server.png`.
* Status bar button text updated from generic `Server: ...` to `Institutional Portal: Stopped`, `Institutional Portal: ● Running (8085)`, etc.
* Wired database modification signals (`books_added`, `books_deleted`) to trigger backend library reload.

### D. Web Portal Admin Navigation
**File:** `customization/frontend/static/js/portal.js`
* When an authenticated Administrator visits `http://127.0.0.1:8085/`, an `Admin Console 🛡` navigation button is automatically injected into the top navigation bar.

### E. Configuration Store Library De-duplication
**File:** `customization/backend/config_manager.py`
* Updated `add_library()`: when setting `is_default=True`, any existing library with that path is updated and other libraries are marked `is_default=0`, preventing multiple default library conflicts.

---

## 4. End-to-End Verification & Test Results

We executed comprehensive automated integration tests (`scripts/verify_institutional_integration.py`):

| Test Item | Expected Result | Actual Result | Status |
| :--- | :--- | :--- | :---: |
| **Active Library Path** | `C:\Users\USER\Calibre Library` | `C:\Users\USER\Calibre Library` (is_active=1, is_default=1) | **PASS** |
| **No Demo Paths** | No references to `C:\dev\...` or `.demo` | Zero `.demo` libraries in database | **PASS** |
| **Institutional Gateway** | Port 8085 starts & responds | HTTP 200 OK | **PASS** |
| **Calibre Backend Loopback** | Port 8088 running | HTTP 200 OK (Calibre server loopback) | **PASS** |
| **Landing Page Branding** | Aethelgard Institute cream/green | "Aethelgard Institute of Technology" rendered | **PASS** |
| **Admin Authentication** | `admin` / `InstitutionalAdmin2026!` | HTTP 200 OK (role: Administrator) | **PASS** |
| **Admin Console Access** | `http://127.0.0.1:8085/admin` | HTTP 200 OK, full dashboard rendered | **PASS** |
| **Book Synchronization** | Adding book in desktop updates portal | 4 books total; added book visible in web catalogue | **PASS** |
| **Native Server Isolation** | Port 8080 unaffected | Stock Calibre server operates independently | **PASS** |

---

## 5. Visual Evidence

Evidence screenshots captured directly from the test run:
* `docs/evidence/screenshot_connect_share_menu.png` (Connect/share menu with Institutional & Native server options)
* `docs/evidence/screenshot_server_dialog.png` (Institutional Server Manager controls dialog)
* `docs/evidence/screenshot_landing_page.png` (Aethelgard cream/green institutional landing page)
* `docs/evidence/screenshot_catalogue_page.png` (High-fidelity catalogue displaying synchronized books)
* `docs/evidence/screenshot_admin_console.png` (Institutional administration portal with health status)

---

## 6. Step-by-Step Guide for the Project Owner

1. **Open Calibre Desktop:**
   * Double click the **Calibre Institutional** desktop icon.
2. **Access Server Controls:**
   * Click the **Institutional Portal** button on the main toolbar, **OR**
   * Click **Connect/share** → **Institutional Server Controls...**
3. **Start the Institutional Server:**
   * In the dialog, click **Start Server**.
   * Status updates to: `● Running` and Address indicates `http://127.0.0.1:8085`.
4. **Visit the Institutional Website:**
   * Click **🌐 Open Library Website** (or select **Connect/share → Open Institutional Library Website**).
   * Your browser opens `http://127.0.0.1:8085/` with the cream/green institutional portal.
5. **Access the Administration Console:**
   * In the dialog, click **🛡 Open Admin Console** (or select **Connect/share → Open Institutional Admin Console**).
   * Log in with:
     * **Username:** `admin`
     * **Password:** `InstitutionalAdmin2026!`
   * You can manage users, update library branding, view activity audit logs, and inspect server diagnostics.

---

## 7. Distribution Package

The Windows installer has been rebuilt using Inno Setup Compiler (`ISCC.exe`):
* **Installer File:** `dist/Calibre-Institutional-Setup.exe`
* **Size:** 268,258,417 bytes (~255.8 MB)
* **SHA-256 Hash:** `51B0374D337D54C20456463CD1ADEDB39188208B4D897A49F3617B132E97A2B3`

### Installation Instructions for the Owner:
1. Close any running Calibre instances.
2. Run `Calibre-Institutional-Setup.exe`.
3. Follow the wizard prompts to install. Existing books and custom configurations in `%LOCALAPPDATA%\CalibreInstitutional` are fully preserved.
