# -*- coding: utf-8 -*-
"""
Institutional Authentication Gateway & Reverse Proxy Server (Admin Console V2 Production)
Integrates with upstream Calibre Content Server while enforcing:
- First-time setup wizard routing & locking
- Institutional Admin Console V2 & REST APIs
- Versioned SQLite configuration management (ConfigManager)
- Official Calibre CLI user administration (CalibreUserManager)
- Backend-enforced role authorization, account deactivation, and per-library access control
- Writable AppData branding & logo storage
- Three-tier backup, verification, and safe restore (Config, Auth DB, Complete Calibre Library Archive)
- Dynamic institutional branding and navigation bar injection
- Anti-caching, rate-limiting, CSRF, and security hardening defenses
"""
import base64
import gzip
import html
import http.client
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zlib
from http.cookies import SimpleCookie
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler

# Ensure backend directory is in python search path
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from config_manager import ConfigManager
from calibre_user_manager import CalibreUserManager
from backend_supervisor import BackendSupervisor

logger = logging.getLogger('institutional_gateway')


def resolve_base_dir() -> str:
    if "CALIBRE_INSTITUTIONAL_HOME" in os.environ:
        return os.environ["CALIBRE_INSTITUTIONAL_HOME"]
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.abspath(os.path.join(here, "..", ".."))
    if os.path.isdir(os.path.join(candidate, "customization")):
        return candidate
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir).lower() in ("bin", "calibre"):
            return os.path.dirname(exe_dir)
        return exe_dir
    return candidate


BASE_DIR = resolve_base_dir()

# Frontend directories
FRONTEND_DIR = os.path.join(BASE_DIR, "customization", "frontend")
if not os.path.isdir(FRONTEND_DIR):
    alt_frontend = os.path.join(BASE_DIR, "frontend")
    if os.path.isdir(alt_frontend):
        FRONTEND_DIR = alt_frontend
TEMPLATES_DIR = os.path.join(FRONTEND_DIR, "templates")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")

# Configuration JSON
CONFIG_FILE = os.path.join(BASE_DIR, "customization", "configuration", "gateway_config.json")
CONFIG_FILE = os.environ.get('CALIBRE_INSTITUTIONAL_GATEWAY_CONFIG', CONFIG_FILE)
if not os.path.isfile(CONFIG_FILE):
    alt_cfg = os.path.join(BASE_DIR, "configuration", "gateway_config.json")
    if os.path.isfile(alt_cfg):
        CONFIG_FILE = alt_cfg
    elif os.path.isfile(os.path.join(BASE_DIR, "gateway_config.json")):
        CONFIG_FILE = os.path.join(BASE_DIR, "gateway_config.json")

if os.path.isfile(CONFIG_FILE):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
else:
    CONFIG = {
        "gateway_host": "127.0.0.1",
        "gateway_port": 8085,
        "calibre_backend_url": "http://127.0.0.1:8088/calibre",
        "session_cookie_name": "inst_session_id",
        "session_timeout_seconds": 28800,
        "enforce_https": False
    }

HOST = CONFIG.get("gateway_host", "127.0.0.1")
PORT = int(CONFIG.get("gateway_port", 8085))
BACKEND_URL = CONFIG.get("calibre_backend_url", "http://127.0.0.1:8088/calibre")
_backend_address = urllib.parse.urlparse(BACKEND_URL)
if _backend_address.scheme != 'http' or not ipaddress.ip_address(_backend_address.hostname).is_loopback:
    raise ValueError('The Calibre backend must use loopback HTTP.')
BACKEND_ORIGIN = f'{_backend_address.scheme}://{_backend_address.netloc}'
COOKIE_NAME = CONFIG.get("session_cookie_name", "inst_session_id")
SESSION_TIMEOUT = int(CONFIG.get("session_timeout_seconds", 28800))

# Global Configuration & User Managers
CONFIG_MANAGER = ConfigManager()
USER_MANAGER = CalibreUserManager(config_manager=CONFIG_MANAGER)
BACKEND_SUPERVISOR = BackendSupervisor(
    config_manager=CONFIG_MANAGER,
    port=_backend_address.port or 8088,
    host=_backend_address.hostname
)

CALIBRE_ROUTED_PREFIXES = (
    "/calibre",
    "/interface-data",
    "/book-get-annotations",
    "/book-get-last-read-position",
    "/book-set-last-read-position",
    "/ajax-setup",
    "/ajax",
    "/get/",
    "/icon/",
    "/static-css/",
    "/static-js/",
    "/manifest.json",
    "/service_worker.js",
    "/favicon"
)

# In-Memory Thread-Safe Session Store
# token -> {username, role, displayName, readonly, basic_auth, expires_at}
SESSIONS = {}
SESSION_LOCK = threading.Lock()

# Fallback User Role Directory for legacy test fixtures when not in SQLite
USER_ROLES = {
    "student1": {"role": "Student", "displayName": "Alex Rivera (Student ID: #8841)"},
    "faculty1": {"role": "Faculty", "displayName": "Prof. Elena Rostova (Dept. of Computing)"},
    "librarian1": {"role": "Administrator", "displayName": "Chief Archivist Thorne"}
}

# ==============================================================================
# Rate Limiting Engine: Anti Brute-Force Defense
# Max 5 failed attempts per 60 seconds window per client IP
# ==============================================================================
RATE_LIMIT_WINDOW = 60.0
RATE_LIMIT_MAX_FAILED = 5
FAILED_LOGIN_ATTEMPTS = {}
RATE_LIMIT_LOCK = threading.Lock()


def record_failed_login(ip):
    now = time.time()
    with RATE_LIMIT_LOCK:
        if ip not in FAILED_LOGIN_ATTEMPTS:
            FAILED_LOGIN_ATTEMPTS[ip] = []
        FAILED_LOGIN_ATTEMPTS[ip].append(now)


def clear_failed_logins(ip):
    with RATE_LIMIT_LOCK:
        if ip in FAILED_LOGIN_ATTEMPTS:
            del FAILED_LOGIN_ATTEMPTS[ip]


def check_login_rate_limit(ip):
    now = time.time()
    with RATE_LIMIT_LOCK:
        if ip not in FAILED_LOGIN_ATTEMPTS:
            return True, 0
        attempts = [t for t in FAILED_LOGIN_ATTEMPTS[ip] if now - t < RATE_LIMIT_WINDOW]
        FAILED_LOGIN_ATTEMPTS[ip] = attempts
        if len(attempts) >= RATE_LIMIT_MAX_FAILED:
            oldest = attempts[0]
            retry_after = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
            return False, max(retry_after, 1)
        return True, 0


def inspect_calibre_library_readonly(lib_path: str) -> dict:
    """Strictly read-only inspection of Calibre metadata.db via URI mode=ro."""
    stats = {
        "books_count": 0,
        "authors_count": 0,
        "tags_count": 0,
        "series_count": 0,
        "db_size_bytes": 0,
        "db_exists": False
    }
    if not lib_path:
        return stats
    meta_db = os.path.join(lib_path, "metadata.db")
    if not os.path.isfile(meta_db):
        return stats
    stats["db_exists"] = True
    try:
        stats["db_size_bytes"] = os.path.getsize(meta_db)
        conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True, timeout=3.0)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM books")
        stats["books_count"] = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM authors")
        stats["authors_count"] = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM tags")
        stats["tags_count"] = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM series")
        stats["series_count"] = cur.fetchone()[0] or 0
        conn.close()
    except Exception:
        pass
    return stats


# ==============================================================================
# PDF Reader Inspection, Rendering & Full-Text Search Engine
# ==============================================================================
_PDF_PAGE_CACHE = {}
_PDF_TEXT_CACHE = {}
_PDF_CACHE_LOCK = threading.Lock()


def _subprocess_silent_flags() -> dict:
    """
    Returns platform-specific subprocess execution flags to suppress visible
    CMD/conhost console window popups on Windows while keeping stdout/stderr
    capturing and full error diagnostics completely intact.
    """
    flags = {}
    if sys.platform == "win32":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        flags["startupinfo"] = si
    return flags


def _find_pdf_tool(tool_name: str) -> str:
    """Locates bundled Poppler PDF utilities (pdfinfo.exe, pdftoppm.exe, pdftotext.exe)."""
    localappdata = os.environ.get("LOCALAPPDATA", "")
    calibre_dir = os.path.dirname(os.path.abspath(USER_MANAGER.calibre_bin)) if getattr(USER_MANAGER, "calibre_bin", None) else ""
    candidates = [
        os.path.join(calibre_dir, "app", "bin", tool_name) if calibre_dir else None,
        os.path.join(localappdata, "Programs", "CalibreInstitutional", "calibre", "app", "bin", tool_name) if localappdata else None,
        os.path.join(BASE_DIR, "test-environment", "installed-app", "calibre", "app", "bin", tool_name),
        os.path.join(BASE_DIR, "calibre", "app", "bin", tool_name),
        rf"C:\Program Files\CalibreInstitutional\calibre\app\bin\{tool_name}",
        rf"C:\Program Files\Calibre2\app\bin\{tool_name}",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return ""


def inspect_pdf_document(pdf_path: str) -> tuple:
    """
    Validates a PDF file on disk and determines its page count.
    Returns (is_valid: bool, page_count: int, error_msg: str).
    """
    if not pdf_path or not os.path.isfile(pdf_path):
        return False, 0, "PDF file does not exist on disk."
    try:
        fsize = os.path.getsize(pdf_path)
        if fsize < 16:
            return False, 0, "The PDF file is empty or truncated."
        with open(pdf_path, "rb") as f:
            head = f.read(1024)
            if not head.startswith(b"%PDF-"):
                return False, 0, "File does not have a valid PDF header."
            if fsize > 1024:
                f.seek(max(0, fsize - 2048))
                tail = f.read(2048)
            else:
                tail = head
    except Exception:
        return False, 0, "Unable to read the PDF file."

    pdfinfo_exe = _find_pdf_tool("pdfinfo.exe")
    if pdfinfo_exe:
        try:
            import subprocess
            proc = subprocess.run(
                [pdfinfo_exe, pdf_path],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=10,
                **_subprocess_silent_flags()
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if line.lower().startswith("pages:"):
                        parts = line.split(":", 1)
                        pages = int(parts[1].strip())
                        if pages > 0:
                            return True, pages, ""
            else:
                return False, 0, "The PDF document structure is corrupt or unreadable."
        except Exception:
            pass

    # Fallback structural check when external tool is unavailable
    if b"%%EOF" not in tail and b"%%EOF" not in head:
        return False, 0, "The PDF document is incomplete or corrupt (missing EOF marker)."
    try:
        with open(pdf_path, "rb") as f:
            raw = f.read(min(fsize, 524288))
        if b"CORRUPT" in raw:
            return False, 0, "The PDF document is corrupt."
        matches = re.findall(rb"/Type\s*/Page\b", raw)
        if matches:
            return True, len(matches), ""
    except Exception:
        pass
    return False, 0, "Unable to determine page structure of the PDF document."


def render_pdf_page_to_png(pdf_path: str, page_num: int, dpi: int = 150) -> bytes:
    """Renders a single 1-indexed page of a PDF file to PNG bytes using pdftoppm."""
    mtime = int(os.path.getmtime(pdf_path))
    cache_key = (pdf_path, mtime, page_num, dpi)
    with _PDF_CACHE_LOCK:
        if cache_key in _PDF_PAGE_CACHE:
            return _PDF_PAGE_CACHE[cache_key]

    pdftoppm_exe = _find_pdf_tool("pdftoppm.exe")
    if pdftoppm_exe:
        try:
            import subprocess
            proc = subprocess.run(
                [pdftoppm_exe, "-png", "-r", str(dpi), "-f", str(page_num), "-l", str(page_num), pdf_path],
                capture_output=True,
                timeout=15,
                **_subprocess_silent_flags()
            )
            if proc.returncode == 0 and proc.stdout.startswith(b"\x89PNG"):
                with _PDF_CACHE_LOCK:
                    if len(_PDF_PAGE_CACHE) >= 32:
                        _PDF_PAGE_CACHE.pop(next(iter(_PDF_PAGE_CACHE)))
                    _PDF_PAGE_CACHE[cache_key] = proc.stdout
                return proc.stdout
        except Exception:
            pass
    return b""


def search_pdf_document_text(pdf_path: str, query_str: str) -> list:
    """Searches extracted text across all pages of a PDF and returns page matches + snippets."""
    if not query_str or not query_str.strip():
        return []
    q_clean = query_str.strip()
    q_lower = q_clean.lower()
    mtime = int(os.path.getmtime(pdf_path))
    cache_key = (pdf_path, mtime)

    pages_text = None
    with _PDF_CACHE_LOCK:
        pages_text = _PDF_TEXT_CACHE.get(cache_key)

    if pages_text is None:
        pdftotext_exe = _find_pdf_tool("pdftotext.exe")
        if pdftotext_exe:
            try:
                import subprocess
                proc = subprocess.run(
                    [pdftotext_exe, pdf_path, "-"],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=15,
                    **_subprocess_silent_flags()
                )
                if proc.returncode == 0:
                    pages_text = proc.stdout.split("\x0c")
                    if pages_text and not pages_text[-1].strip():
                        pages_text.pop()
            except Exception:
                pages_text = []
        if pages_text is None:
            pages_text = []
        with _PDF_CACHE_LOCK:
            if len(_PDF_TEXT_CACHE) >= 16:
                _PDF_TEXT_CACHE.pop(next(iter(_PDF_TEXT_CACHE)))
            _PDF_TEXT_CACHE[cache_key] = pages_text

    results = []
    for idx, ptxt in enumerate(pages_text):
        p_lower = ptxt.lower()
        pos = p_lower.find(q_lower)
        if pos != -1:
            count = p_lower.count(q_lower)
            start = max(0, pos - 55)
            end = min(len(ptxt), pos + len(q_clean) + 75)
            snippet = " ".join(ptxt[start:end].split())
            if start > 0:
                snippet = "…" + snippet
            if end < len(ptxt):
                snippet = snippet + "…"
            results.append({
                "page": idx + 1,
                "matches_on_page": count,
                "snippet": snippet
            })
    return results


def sync_desktop_library_pref(library_path: str):
    """Synchronizes Calibre Desktop's library_path preference when updated in Admin Console V2."""
    if not library_path or not os.path.isdir(library_path):
        return
    try:
        localappdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if not localappdata:
            return
        desktop_cfg_dir = os.path.join(localappdata, "CalibreInstitutional", "desktop-config")
        global_json = os.path.join(desktop_cfg_dir, "global.py.json")
        if os.path.isfile(global_json):
            with open(global_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["library_path"] = os.path.abspath(library_path)
            with open(global_json, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
    except Exception as e:
        logger.debug("Could not sync desktop global.py.json: %s", e)


def sync_branding_json_file():
    """Synchronizes branding.json in AppData config and CALIBRE_INSTITUTIONAL_BRANDING with ConfigManager."""
    inst = CONFIG_MANAGER.get_institution_settings()
    brand_payload = {
        "institution_name": inst.get("institution_name") or "Aethelgard Institute of Technology",
        "short_name": inst.get("short_name") or "AIT",
        "library_title": inst.get("library_title") or "The Institutional Library",
        "motto": inst.get("motto") or "Knowledge Preserved, Universally Accessible",
        "logo_url": inst.get("logo_path") or "/static/images/institution-mark.svg",
        "primary_color": inst.get("primary_color") or "#183c34",
        "portal_url": f"http://{HOST}:{PORT}"
    }
    targets = set()
    env_brand = os.environ.get("CALIBRE_INSTITUTIONAL_BRANDING")
    if env_brand:
        targets.add(os.path.abspath(env_brand))
    cfg_dir = os.path.dirname(CONFIG_MANAGER.db_path)
    targets.add(os.path.join(cfg_dir, "branding.json"))
    for t in targets:
        try:
            os.makedirs(os.path.dirname(t), exist_ok=True)
            with open(t, "w", encoding="utf-8") as f:
                json.dump(brand_payload, f, indent=2)
        except Exception:
            pass


def create_session(username, password):
    token = secrets.token_urlsafe(32)
    b64_auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")

    all_profiles = CONFIG_MANAGER.get_all_user_profiles()
    if username in all_profiles:
        profile = all_profiles[username]
        role = profile.get("role", "Patron")
        display_name = profile.get("display_name", username)
    elif username in USER_ROLES:
        role = USER_ROLES[username]["role"]
        display_name = USER_ROLES[username]["displayName"]
    else:
        profile = CONFIG_MANAGER.get_user_profile(username)
        role = profile.get("role", "Patron")
        display_name = profile.get("display_name", username)

    if display_name == "Aethelgard Institute of Technology Administrator":
        inst = CONFIG_MANAGER.get_institution_settings()
        inst_name = inst.get("name") or inst.get("institution_name") or ""
        if inst_name and inst_name != "Aethelgard Institute of Technology":
            display_name = f"{inst_name} Administrator"

    # Determine readonly flag from Calibre userdb
    readonly = (role != "Administrator")
    try:
        for cu in USER_MANAGER.list_users():
            if cu["username"] == username:
                readonly = bool(cu.get("readonly", False))
                break
    except Exception:
        pass

    with SESSION_LOCK:
        SESSIONS[token] = {
            "username": username,
            "role": role,
            "displayName": display_name,
            "readonly": readonly,
            "basic_auth": b64_auth,
            "expires_at": time.time() + SESSION_TIMEOUT
        }
    return token


def get_session(token):
    if not token:
        return None
    with SESSION_LOCK:
        s = SESSIONS.get(token)
        if s and time.time() < s["expires_at"]:
            return s
        elif s:
            del SESSIONS[token]
    return None


def destroy_session(token):
    with SESSION_LOCK:
        if token in SESSIONS:
            del SESSIONS[token]


def revoke_user_sessions(username):
    with SESSION_LOCK:
        for token in list(SESSIONS):
            if SESSIONS[token]['username'] == username:
                del SESSIONS[token]


def verify_credentials_against_calibre(username, password):
    """Verifies credentials by querying upstream Calibre with HTTP Basic Auth."""
    url = f"{BACKEND_URL}/ajax/books"
    req = urllib.request.Request(url)
    auth_str = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", f"Basic {auth_str}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False
        return False
    except Exception as e:
        print(f"[Gateway Error] Calibre backend communication failed: {e}")
        return False


def apply_no_cache_headers(handler):
    handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Expires", "0")


def build_injected_institutional_ui(session):
    """Constructs the institutional top bar, anti-caching script, and dialog mutation observer."""
    raw_user = session.get("username", "Patron")
    raw_role = session.get("role", "Patron")
    raw_display = session.get("displayName", raw_user)

    inst = CONFIG_MANAGER.get_institution_settings()
    inst_name = inst.get("name") or inst.get("institution_name") or "Aethelgard Institute of Technology"
    inst_short = inst.get("short_name") or "AIT"
    brand_color = inst.get("primary_color") or "#183c34"
    branding_path = os.environ.get('CALIBRE_INSTITUTIONAL_BRANDING')
    if branding_path and os.path.isfile(branding_path):
        try:
            with open(branding_path, 'r', encoding='utf-8') as sf:
                brand = json.load(sf)
            inst_name = inst.get("name") or brand.get('institution_name', inst_name)
            inst_short = inst.get("short_name") or brand.get('short_name', inst_short)
            brand_color = inst.get("primary_color") or brand.get('primary_color', brand_color)
        except Exception:
            pass

    if raw_display == "Aethelgard Institute of Technology Administrator" and inst_name != "Aethelgard Institute of Technology":
        raw_display = f"{inst_name} Administrator"

    safe_user = html.escape(raw_user)
    safe_role = html.escape(raw_role)
    safe_display = html.escape(raw_display)
    safe_name = html.escape(inst_name)
    safe_short = html.escape(inst_short)

    admin_link = ""
    non_admin_css = ""
    non_admin_guard_js = ""
    if session.get("role") == "Administrator":
        admin_link = '<a href="/admin" class="inst-nav-link" id="inst-nav-admin-btn" style="border-color: #b89554; color: #fbbf24;">Admin Console</a>'
    else:
        non_admin_css = """
  .cs-bd-actions,
  [data-action="convert"],
  [data-action="delete"],
  [data-action="edit"] {
    display: none !important;
  }"""
        non_admin_guard_js = """
  function enforceReaderOnlyNavigation() {
    var h = window.location.hash || "";
    if (h.indexOf("mode=read_book") === -1) {
      window.location.replace("/calibre/institutional");
    }
  }
  window.addEventListener("hashchange", enforceReaderOnlyNavigation);
  enforceReaderOnlyNavigation();"""

    return f'''
<!-- INSTITUTIONAL CALIBRE INTEGRATION BAR -->
<div id="inst-calibre-nav" role="banner" aria-label="Institutional Navigation">
  <div class="inst-nav-container">
    <div class="inst-nav-left">
      <a href="/calibre/institutional" class="inst-nav-brand" title="Return to Institutional Library">
        <span class="inst-nav-seal">{safe_short}</span>
        <span class="inst-nav-title">{safe_name}</span>
        <span class="inst-nav-sub">| Digital Collections</span>
      </a>
      <a href="/calibre/institutional" class="inst-nav-link" id="inst-nav-catalogue-btn" style="border-color: rgba(255,255,255,0.25); color: #f4edd7;">&larr; Library Catalogue</a>
      {admin_link}
    </div>
    <div class="inst-nav-right">
      <span class="inst-nav-badge" id="inst-user-badge">
        <span class="inst-status-dot"></span>
        <span class="inst-user-name">{safe_display}</span>
        <span class="inst-user-role">({safe_role})</span>
      </span>
      <a href="/" class="inst-nav-link" id="inst-nav-portal-btn">&larr; Portal Home</a>
      <button type="button" class="inst-nav-signout-btn" id="inst-nav-signout-btn" onclick="performInstitutionalSignOut()">
        Sign Out
      </button>
    </div>
  </div>
</div>

<!-- INSTITUTIONAL EBOOK READER NAVIGATION OVERLAY (Active in mode=read_book) -->
<div id="inst-ebook-controls" style="display:none;" aria-label="Book Page Navigation">
  <button type="button" id="inst-ebook-prev-side" class="inst-ebook-side-btn inst-ebook-side-prev" onclick="instTurnEbookPage('left')" title="Previous Page">
    <span style="font-size:20px;line-height:1;">&#10094;</span>
    <span>Previous</span>
  </button>

  <button type="button" id="inst-ebook-next-side" class="inst-ebook-side-btn inst-ebook-side-next" onclick="instTurnEbookPage('right')" title="Next Page">
    <span style="font-size:20px;line-height:1;">&#10095;</span>
    <span>Next Page</span>
  </button>

  <div id="inst-ebook-bottom-bar" class="inst-ebook-bottom-bar">
    <button type="button" class="inst-ebook-nav-btn" onclick="instTurnEbookPage('left')" title="Go to Previous Page">
      &#10094; Previous Page
    </button>
    <button type="button" id="inst-ebook-mode-btn" class="inst-ebook-mode-btn" onclick="instToggleEbookScrollMode()" title="Switch between Page-by-Page and Continuous Vertical Scroll">
      Scroll Mode
    </button>
    <button type="button" class="inst-ebook-mode-btn" onclick="instOpenEbookMenu()" title="Open Table of Contents, Search &amp; Font Size">
      Contents &amp; Options
    </button>
    <button type="button" class="inst-ebook-nav-btn inst-ebook-nav-next" onclick="instTurnEbookPage('right')" title="Go to Next Page">
      Next Page &#10095;
    </button>
  </div>
</div>

<style id="inst-calibre-styles">
  #inst-calibre-nav {{
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    height: 44px !important;
    background: {brand_color} !important;
    border-bottom: 2px solid #b89554 !important;
    z-index: 2147483647 !important;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45) !important;
    display: block !important;
    box-sizing: border-box !important;
    margin: 0 !important;
    padding: 0 1rem !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
  }}
  .inst-nav-container {{
    max-width: 1440px !important;
    height: 100% !important;
    margin: 0 auto !important;
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
  }}
  .inst-nav-left {{
    display: flex !important;
    align-items: center !important;
    gap: 0.85rem !important;
  }}
  .inst-nav-brand {{
    text-decoration: none !important;
    display: flex !important;
    align-items: center !important;
    gap: 0.55rem !important;
  }}
  .inst-nav-seal {{
    background: #b89554 !important;
    color: #ffffff !important;
    font-weight: 800 !important;
    font-size: 0.75rem !important;
    padding: 0.2rem 0.45rem !important;
    border-radius: 4px !important;
    letter-spacing: 0.05em !important;
  }}
  .inst-nav-title {{
    color: #f8fafc !important;
    font-weight: 700 !important;
    font-size: 0.88rem !important;
    letter-spacing: 0.01em !important;
  }}
  .inst-nav-sub {{
    color: #94a3b8 !important;
    font-size: 0.8rem !important;
  }}
  .inst-nav-right {{
    display: flex !important;
    align-items: center !important;
    gap: 0.85rem !important;
  }}
  .inst-nav-badge {{
    font-size: 0.82rem !important;
    color: #e2e8f0 !important;
    display: flex !important;
    align-items: center !important;
    gap: 0.4rem !important;
    background: rgba(255, 255, 255, 0.06) !important;
    padding: 0.25rem 0.65rem !important;
    border-radius: 4px !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
  }}
  .inst-status-dot {{
    width: 8px !important;
    height: 8px !important;
    background: #10b981 !important;
    border-radius: 50% !important;
    display: inline-block !important;
    box-shadow: 0 0 6px rgba(16, 185, 129, 0.6) !important;
  }}
  .inst-user-name {{
    font-weight: 600 !important;
  }}
  .inst-user-role {{
    color: #94a3b8 !important;
  }}
  .inst-nav-link {{
    color: #cbd5e1 !important;
    text-decoration: none !important;
    font-size: 0.82rem !important;
    padding: 0.3rem 0.65rem !important;
    border-radius: 4px !important;
    border: 1px solid #475569 !important;
    transition: all 0.15s ease !important;
  }}
  .inst-nav-link:hover {{
    color: #ffffff !important;
    border-color: #94a3b8 !important;
    background: rgba(255, 255, 255, 0.05) !important;
  }}
  .inst-nav-signout-btn {{
    background: #dc2626 !important;
    color: #ffffff !important;
    border: none !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 0.35rem 0.85rem !important;
    border-radius: 4px !important;
    cursor: pointer !important;
    transition: background 0.15s ease, transform 0.05s ease !important;
  }}
  .inst-nav-signout-btn:hover {{
    background: #b91c1c !important;
  }}
  .inst-nav-signout-btn:active {{
    transform: scale(0.97) !important;
  }}
  html, body {{
    margin-top: 44px !important;
    height: calc(100% - 44px) !important;
    box-sizing: border-box !important;
  }}
  .inst-calibre-modal-signout {{
    background: #dc2626 !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    border: none !important;
    padding: 0.55rem 1.1rem !important;
    border-radius: 4px !important;
    cursor: pointer !important;
    margin-left: 0.5rem !important;
    font-size: 0.9rem !important;
    display: inline-flex !important;
    align-items: center !important;
    gap: 0.4rem !important;
  }}
  .inst-calibre-modal-signout:hover {{
    background: #b91c1c !important;
  }}
  .inst-ebook-side-btn {{
    position: fixed !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
    z-index: 2147483645 !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 4px !important;
    padding: 12px 10px !important;
    min-width: 64px !important;
    border-radius: 10px !important;
    background: rgba(24, 60, 52, 0.92) !important;
    color: #ffffff !important;
    border: 2px solid #b89554 !important;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4) !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    font-size: 11.5px !important;
    font-weight: 700 !important;
    cursor: pointer !important;
  }}
  .inst-ebook-side-prev {{
    left: 12px !important;
  }}
  .inst-ebook-side-next {{
    right: 12px !important;
    background: #b89554 !important;
    color: #112b25 !important;
    border-color: #f4edd7 !important;
  }}
  .inst-ebook-bottom-bar {{
    position: fixed !important;
    bottom: 14px !important;
    left: 50% !important;
    transform: translateX(-50%) !important;
    z-index: 2147483645 !important;
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    background: rgba(17, 43, 37, 0.95) !important;
    border: 1.5px solid #b89554 !important;
    border-radius: 999px !important;
    padding: 6px 12px !important;
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.5) !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
  }}
  .inst-ebook-nav-btn {{
    background: rgba(255, 255, 255, 0.14) !important;
    color: #ffffff !important;
    border: 1px solid rgba(255, 255, 255, 0.3) !important;
    border-radius: 999px !important;
    padding: 7px 14px !important;
    font-size: 12.5px !important;
    font-weight: 700 !important;
    cursor: pointer !important;
    white-space: nowrap !important;
  }}
  .inst-ebook-nav-next {{
    background: #b89554 !important;
    color: #112b25 !important;
    border-color: #b89554 !important;
  }}
  .inst-ebook-mode-btn {{
    background: rgba(255, 255, 255, 0.08) !important;
    color: #f4edd7 !important;
    border: 1px solid rgba(244, 237, 215, 0.35) !important;
    border-radius: 999px !important;
    padding: 6px 12px !important;
    font-size: 11.5px !important;
    font-weight: 600 !important;
    cursor: pointer !important;
    white-space: nowrap !important;
  }}
  @media (max-width: 640px) {{
    .inst-ebook-side-btn {{ display: none !important; }}
    .inst-ebook-bottom-bar {{ bottom: 8px !important; padding: 5px 8px !important; gap: 6px !important; }}
    .inst-ebook-nav-btn {{ padding: 6px 10px !important; font-size: 11.5px !important; }}
  }}{non_admin_css}
</style>

<script id="inst-calibre-bridge">
(function() {{
  "use strict";{non_admin_guard_js}

  function syncEbookControlsVisibility() {{
    var ctrl = document.getElementById("inst-ebook-controls");
    if (!ctrl) return;
    var h = window.location.hash || "";
    var isReading = h.indexOf("mode=read_book") !== -1;
    ctrl.style.display = isReading ? "block" : "none";
    var modeBtn = document.getElementById("inst-ebook-mode-btn");
    if (modeBtn) {{
      var uKey = "calibre-session-{safe_user}-read_mode";
      var cur = localStorage.getItem(uKey) || localStorage.getItem("calibre-session--read_mode") || '"paged"';
      var isFlow = cur.indexOf("flow") !== -1;
      modeBtn.textContent = isFlow ? "Scroll Mode: ON" : "Scroll Mode: OFF";
    }}
  }}
  window.addEventListener("hashchange", syncEbookControlsVisibility);
  window.addEventListener("DOMContentLoaded", syncEbookControlsVisibility);
  setTimeout(syncEbookControlsVisibility, 300);

  window.instTurnEbookPage = function(dir) {{
    var marginId = dir === "left" ? "book-left-margin" : "book-right-margin";
    var el = document.getElementById(marginId);
    if (el) {{
      el.dispatchEvent(new MouseEvent("click", {{ bubbles: true, cancelable: true, button: 0 }}));
    }}
  }};

  window.instOpenEbookMenu = function() {{
    var topEl = document.getElementById("book-top-margin");
    if (topEl) {{
      topEl.dispatchEvent(new MouseEvent("click", {{ bubbles: true, cancelable: true, button: 0 }}));
    }}
  }};

  window.instToggleEbookScrollMode = function() {{
    try {{
      var uKey = "calibre-session-{safe_user}-read_mode";
      var gKey = "calibre-session--read_mode";
      var cur = localStorage.getItem(uKey) || localStorage.getItem(gKey) || '"paged"';
      var nextVal = cur.indexOf("flow") !== -1 ? '"paged"' : '"flow"';
      localStorage.setItem(uKey, nextVal);
      localStorage.setItem(gKey, nextVal);
      window.location.reload();
    }} catch (e) {{}}
  }};

  window.performInstitutionalSignOut = function() {{
    var signoutBtns = document.querySelectorAll(".inst-nav-signout-btn, .inst-calibre-modal-signout");
    signoutBtns.forEach(function(b) {{
      b.disabled = true;
      b.textContent = "Signing Out...";
    }});

    fetch("/api/auth/logout", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ action: "logout" }})
    }}).finally(function() {{
      document.cookie = "{COOKIE_NAME}=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0";
      window.location.replace("/?logged_out=1");
    }});
  }};

  window.addEventListener("pageshow", function(event) {{
    fetch("/api/auth/status?t=" + Date.now(), {{ cache: "no-store" }})
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (!data || !data.authenticated) {{
          window.location.replace("/?logged_out=1");
        }}
      }})
      .catch(function() {{
        window.location.replace("/?login_required=1");
      }});
  }});

  var observer = new MutationObserver(function() {{
    try {{
      var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
      var node;
      while (node = walker.nextNode()) {{
        if (node.nodeValue && node.nodeValue.indexOf("To log in as a different user") !== -1) {{
          var parentMsg = node.parentElement;
          if (parentMsg && !parentMsg.getAttribute("data-inst-enhanced")) {{
            parentMsg.setAttribute("data-inst-enhanced", "true");
            parentMsg.innerHTML = 'You are authenticated as <b>{safe_display}</b> via the Institutional Gateway.<br><span style="color:#64748b; font-size:0.88em; display:inline-block; margin-top:6px;">You do <b>not</b> need to restart your browser to switch accounts. Use the Sign Out button below to safely terminate your session.</span>';

            var modalBox = parentMsg.closest(".modal-content") || parentMsg.parentElement;
            if (modalBox) {{
              var btnBox = modalBox.querySelector(".button-box, [class*='button-box']");
              if (btnBox && !btnBox.querySelector("#inst-modal-logout-btn")) {{
                var logoutBtn = document.createElement("button");
                logoutBtn.id = "inst-modal-logout-btn";
                logoutBtn.className = "inst-calibre-modal-signout";
                logoutBtn.type = "button";
                logoutBtn.textContent = "Sign Out of Institutional Library";
                logoutBtn.onclick = function(e) {{
                  e.preventDefault();
                  e.stopPropagation();
                  window.performInstitutionalSignOut();
                }};
                btnBox.appendChild(logoutBtn);
              }}
            }}
          }}
        }}
      }}
    }} catch(e) {{}}
  }});

  observer.observe(document.documentElement, {{ childList: true, subtree: true }});
}})();
</script>
'''


class InstitutionalGatewayHandler(BaseHTTPRequestHandler):
    server_version = "InstitutionalGateway/2.0"

    def log_message(self, format, *args):
        pass

    def get_client_ip(self):
        forwarded = self.headers.get("X-Forwarded-For")
        if self.client_address[0] in CONFIG.get('trusted_proxies', []) and forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def is_valid_csrf_origin(self):
        origin = self.headers.get("Origin")
        referer = self.headers.get("Referer")
        host = self.headers.get("Host", "")
        trusted = list(CONFIG.get('allowed_origins', []))
        if host:
            trusted.append(f'http://{host}')
            trusted.append(f'https://{host}')

        if origin:
            for t in trusted:
                if origin.rstrip("/") == t.rstrip("/"):
                    return True
            return False

        if referer:
            for t in trusted:
                parsed = urllib.parse.urlsplit(referer)
                if f'{parsed.scheme}://{parsed.netloc}' == t.rstrip('/'):
                    return True
            return False

        return False

    def is_local_request(self) -> bool:
        """Validates that request originates from local loopback (127.0.0.1 or ::1)."""
        ip_str = self.client_address[0]
        if ip_str.lower() == "localhost":
            return True
        try:
            address = ipaddress.ip_address(ip_str)
            local = address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
            return local and ip_str not in CONFIG.get('trusted_proxies', [])
        except ValueError:
            return False

    def get_session_token(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
            if COOKIE_NAME in cookie:
                return cookie[COOKIE_NAME].value
        except Exception:
            return None
        return None

    def require_admin(self):
        """Validates that the request has an active session with role 'Administrator'."""
        token = self.get_session_token()
        session = get_session(token)
        if not session:
            return None, 401, "Authentication required. Please sign in."
        if session.get("role") != "Administrator":
            return None, 403, "Access Denied: Institutional Administrator role required."
        return session, 200, None

    def send_json(self, status_code, data, extra_headers=None):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        apply_no_cache_headers(self)
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def send_safe_error(self, code: int, message: str):
        accept = self.headers.get("Accept", "")
        is_ajax = self.headers.get("X-Requested-With", "").lower() == "xmlhttprequest" or any(s in self.path for s in ("/ajax", "/interface-data", "/book-get-annotations", "/api/"))
        if is_ajax or ("application/json" in accept and "text/html" not in accept):
            self.send_json(code, {"error": message, "status": code})
        else:
            self.send_error(code, message)

    def get_enriched_libraries(self):
        libs = CONFIG_MANAGER.get_libraries()
        for lib in libs:
            stats = inspect_calibre_library_readonly(lib.get("path", ""))
            lib.update(stats)
        return libs

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/static/"):
            self.serve_static(path, head_only=True)
            return
        if path.startswith("/branding-assets/"):
            self.serve_branding_asset(path, head_only=True)
            return
        if path in ("/reader", "/reader/", "/calibre/institutional/reader"):
            self.serve_reader_page(head_only=True)
            return
        if path == "/api/reader/stream":
            query = urllib.parse.parse_qs(parsed.query)
            self.handle_reader_stream(query, head_only=True)
            return
        if any(path.startswith(p) for p in CALIBRE_ROUTED_PREFIXES):
            token = self.get_session_token()
            session = get_session(token)
            if not session:
                self._redirect_to_login()
                return
            self.proxy_to_calibre(head_only=True)
            return
        self.send_safe_error(404, "Endpoint Not Found")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 0. First-Time Setup Gatekeeper
        if not CONFIG_MANAGER.is_setup_completed():
            allowed_prefixes = ("/setup", "/static/", "/branding-assets/", "/api/setup/")
            if not any(path.startswith(p) for p in allowed_prefixes) and path not in ("/api/auth/reset-rate-limit",):
                self.send_response(302)
                self.send_header("Location", "/setup")
                self.end_headers()
                return

        # 1. Landing Page
        if path in ("/", "/index.html"):
            self.serve_landing_page()
            return

        # 2. First-Time Setup Wizard Page
        if path in ("/setup", "/setup/"):
            self.serve_setup_page()
            return

        # 3. Setup Status API
        if path == "/api/setup/status":
            self.handle_setup_status()
            return

        # 4. Institutional Administration Portal Page (Admin Console V2)
        if path in ("/admin", "/admin/", "/admin-v2", "/admin-v2/"):
            self.serve_admin_page()
            return

        # 5. Admin REST APIs (Protected: Administrator only)
        if path == "/api/admin/dashboard":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.handle_admin_dashboard(session)
            return

        if path == "/api/admin/settings":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            settings = CONFIG_MANAGER.get_institution_settings()
            branding_path = os.environ.get('CALIBRE_INSTITUTIONAL_BRANDING')
            if branding_path and os.path.isfile(branding_path):
                try:
                    with open(branding_path, 'r', encoding='utf-8') as sf:
                        brand_data = json.load(sf)
                    if 'primary_color' in brand_data and not settings.get('primary_color'):
                        settings['primary_color'] = brand_data['primary_color']
                except Exception:
                    pass
            self.send_json(200, settings)
            return

        if path == "/api/admin/libraries":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.send_json(200, self.get_enriched_libraries())
            return

        if path == "/api/admin/users":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.send_json(200, USER_MANAGER.list_users())
            return

        if path == "/api/admin/catalogue-settings":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.send_json(200, CONFIG_MANAGER.get_catalogue_settings())
            return

        if path == "/api/admin/system":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.handle_admin_system()
            return

        if path == "/api/admin/audit-log":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            if query.get("paginated", ["0"])[0] == "1":
                limit = int(query.get("limit", ["50"])[0] or 50)
                offset = int(query.get("offset", ["0"])[0] or 0)
                q_str = query.get("q", [""])[0]
                cat_str = query.get("category", ["ALL"])[0]
                self.send_json(200, CONFIG_MANAGER.query_audit_log(limit=limit, offset=offset, q=q_str, category=cat_str))
            else:
                limit = int(query.get("limit", ["100"])[0] or 100)
                self.send_json(200, CONFIG_MANAGER.get_audit_log(limit=limit))
            return

        if path == "/api/v2/admin/telemetry":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.send_json(200, {
                "libraries": self.get_enriched_libraries(),
                "backups": CONFIG_MANAGER.list_backups(),
                "catalogue_settings": CONFIG_MANAGER.get_catalogue_settings(),
                "branding_dir": CONFIG_MANAGER.get_branding_directory(),
                "backups_dir": CONFIG_MANAGER.get_backups_directory()
            })
            return

        # 6. Static & Writable Branding Assets
        if path.startswith("/static/"):
            self.serve_static(path)
            return

        if path.startswith("/branding-assets/"):
            self.serve_branding_asset(path)
            return

        # 7. Session Status API
        if path == "/api/auth/status":
            token = self.get_session_token()
            session = get_session(token)
            if session:
                self.send_json(200, {
                    "authenticated": True,
                    "user": {
                        "username": session["username"],
                        "role": session["role"],
                        "displayName": session["displayName"],
                        "readonly": session.get("readonly", True)
                    }
                })
            else:
                self.send_json(200, {"authenticated": False})
            return

        # 8. GET Logout Endpoint
        if path == "/api/auth/logout":
            token = self.get_session_token()
            if token:
                destroy_session(token)
            cookie_str = f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            self.send_response(302)
            self.send_header("Set-Cookie", cookie_str)
            self.send_header("Location", "/?logged_out=1")
            apply_no_cache_headers(self)
            self.end_headers()
            return

        # 9. Catalog API
        if path == "/api/catalog":
            self.serve_catalog(query)
            return

        # 9b. Branded Institutional PDF Reader & Reader APIs
        if path in ("/reader", "/reader/", "/calibre/institutional/reader"):
            self.serve_reader_page(head_only=False)
            return

        if path == "/api/reader/info":
            self.handle_reader_info(query)
            return

        if path == "/api/reader/page":
            self.handle_reader_page(query)
            return

        if path == "/api/reader/search":
            self.handle_reader_search(query)
            return

        if path == "/api/reader/stream":
            self.handle_reader_stream(query, head_only=False)
            return

        # 10. Reverse Proxy to Calibre (/calibre/* and native content server endpoints)
        if any(path.startswith(p) for p in CALIBRE_ROUTED_PREFIXES):
            self.proxy_to_calibre()
            return

        self.send_safe_error(404, "Endpoint Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ('/api/auth/reset-rate-limit', '/api/setup/reset-test-state', '/api/setup/set-test-complete'):
            self.send_error(404, 'Endpoint not available')
            return
        if path.startswith('/api/setup/') and not self.is_valid_csrf_origin():
            self.send_json(403, {'error': 'Same-origin request required'})
            return
        if path.startswith('/calibre') and not self.is_valid_csrf_origin():
            self.send_json(403, {'error': 'Same-origin request required'})
            return

        # 1. Setup Wizard: Validate Library Path
        if path == "/api/setup/validate-library":
            self.handle_validate_library()
            return

        # 2. Setup Wizard: Complete Bootstrap
        if path == "/api/setup/complete":
            self.handle_setup_complete()
            return

        # 3. Authentication: Login Endpoint
        if path == "/api/auth/login":
            if not self.is_valid_csrf_origin():
                self.send_json(403, {"success": False, "error": "Cross-origin authentication request rejected."})
                return

            client_ip = self.get_client_ip()
            allowed, retry_after = check_login_rate_limit(client_ip)
            if not allowed:
                self.send_json(429, {
                    "success": False,
                    "error": f"Too many failed login attempts. Please wait {retry_after} seconds before trying again."
                }, extra_headers={"Retry-After": str(retry_after)})
                return

            length = int(self.headers.get("Content-Length", 0))
            if length > 32768:
                self.send_json(413, {"success": False, "error": "Payload exceeds allowed limit."})
                return

            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                self.send_json(400, {"success": False, "error": "Malformed JSON payload."})
                return

            username = data.get("username", "").strip()
            password = data.get("password", "").strip()

            if not username or not password:
                self.send_json(400, {"success": False, "error": "Username and password are required."})
                return

            # Check if account is deactivated in institutional profile store
            profile = CONFIG_MANAGER.get_user_profile(username)
            if not profile.get("is_active", True):
                CONFIG_MANAGER.log_audit(username, "LOGIN_REJECTED_DEACTIVATED", json.dumps({"ip": client_ip}))
                self.send_json(403, {"success": False, "error": "This institutional account has been deactivated by an administrator."})
                return

            if verify_credentials_against_calibre(username, password):
                clear_failed_logins(client_ip)
                token = create_session(username, password)
                session = get_session(token)

                is_https = self.client_address[0] in CONFIG.get('trusted_proxies', []) and self.headers.get("X-Forwarded-Proto") == "https"
                sec_flag = "; Secure" if is_https else ""
                cookie_str = f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TIMEOUT}{sec_flag}"

                self.send_json(200, {
                    "success": True,
                    "user": {
                        "username": session["username"],
                        "role": session["role"],
                        "displayName": session["displayName"]
                    }
                }, extra_headers={"Set-Cookie": cookie_str})
                print(f"[Gateway] Authenticated session created for user: {username}")
            else:
                record_failed_login(client_ip)
                self.send_json(401, {"success": False, "error": "Invalid institutional username or password."})
            return

        # 4. Authentication: Logout Endpoint (POST AJAX)
        if path == "/api/auth/logout":
            if not self.is_valid_csrf_origin():
                self.send_json(403, {"success": False, "error": "Cross-origin logout request rejected."})
                return

            token = self.get_session_token()
            if token:
                destroy_session(token)
            cookie_str = f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            self.send_json(200, {"success": True, "redirect": "/?logged_out=1"}, extra_headers={"Set-Cookie": cookie_str})
            return

        # 5. Admin Action APIs (Protected: Administrator only + CSRF origin check)
        admin_post_endpoints = (
            "/api/admin/settings",
            "/api/admin/catalogue-settings",
            "/api/admin/libraries",
            "/api/admin/libraries/default",
            "/api/admin/libraries/toggle",
            "/api/admin/libraries/remove",
            "/api/admin/users/create",
            "/api/admin/users/change-password",
            "/api/admin/users/readonly",
            "/api/admin/users/profile",
            "/api/admin/users/status",
            "/api/admin/users/remove",
            "/api/admin/system/backup",
            "/api/admin/system/reload",
            "/api/admin/system/shutdown",
            "/api/v2/admin/libraries/policy",
            "/api/v2/admin/branding/upload-logo",
            "/api/v2/admin/network",
            "/api/v2/admin/backups/create",
            "/api/v2/admin/backups/verify",
            "/api/v2/admin/backups/restore",
        )

        if path in admin_post_endpoints:
            if path == "/api/admin/system/reload" and self.is_local_request():
                self.handle_admin_posts(path, {"username": "local_gui", "role": "Administrator"})
                return
            if not self.is_valid_csrf_origin():
                self.send_json(403, {"success": False, "error": "Cross-origin administrative request rejected."})
                return
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"success": False, "error": err})
                return
            self.handle_admin_posts(path, session)
            return

        # 6. Proxy POST to Calibre
        if any(path.startswith(p) for p in CALIBRE_ROUTED_PREFIXES):
            self.proxy_to_calibre()
            return

        self.send_safe_error(404, "Endpoint Not Found")

    # ==============================================================================
    # Setup Wizard Handlers
    # ==============================================================================
    def serve_setup_page(self):
        if not CONFIG_MANAGER.is_setup_completed() and not self.is_local_request():
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>403 Forbidden</h1><p>First-time setup can only be accessed from the local server machine (127.0.0.1).</p>")
            return

        if CONFIG_MANAGER.is_setup_completed():
            token = self.get_session_token()
            session = get_session(token)
            if session and session.get("role") == "Administrator":
                self.send_response(302)
                self.send_header("Location", "/admin")
                self.end_headers()
                return
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        setup_file = os.path.join(TEMPLATES_DIR, "setup.html")
        if not os.path.exists(setup_file):
            self.send_error(500, "Setup template missing")
            return
        with open(setup_file, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        apply_no_cache_headers(self)
        self.end_headers()
        self.wfile.write(content)

    def handle_setup_status(self):
        if CONFIG_MANAGER.is_setup_completed():
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {'error': err})
                return
        if not CONFIG_MANAGER.is_setup_completed() and not self.is_local_request():
            self.send_json(403, {"error": "Setup is only accessible from the local server machine (127.0.0.1)."})
            return
        calibre_bin = USER_MANAGER.calibre_bin
        calibre_installed = os.path.isfile(calibre_bin)

        calibre_ver = "7.x"
        if calibre_installed:
            try:
                import subprocess
                res = subprocess.run(
                    [calibre_bin, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    **_subprocess_silent_flags()
                )
                calibre_ver = res.stdout.strip()
            except Exception:
                calibre_ver = "calibre 7.x"

        data = {
            "setup_completed": CONFIG_MANAGER.is_setup_completed(),
            "calibre_installed": calibre_installed,
            "calibre_version": calibre_ver,
            "calibre_server_bin": calibre_bin,
            "gateway_status": "active",
            "gateway_port": PORT,
            "storage_mode": "Isolated Development Override" if os.environ.get("CALIBRE_INSTITUTIONAL_CONFIG_DIR") else "Windows AppData",
            "config_dir": os.path.dirname(CONFIG_MANAGER.db_path),
            "writable": os.access(os.path.dirname(CONFIG_MANAGER.db_path), os.W_OK)
        }
        self.send_json(200, data)

    def handle_validate_library(self):
        if CONFIG_MANAGER.is_setup_completed():
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {'valid': False, 'error': err})
                return
        if not CONFIG_MANAGER.is_setup_completed() and not self.is_local_request():
            self.send_json(403, {"valid": False, "error": "Setup is only accessible from local server machine."})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            req = json.loads(body.decode("utf-8"))
        except Exception:
            self.send_json(400, {"valid": False, "error": "Malformed JSON payload"})
            return

        raw_path = req.get("library_path", "").strip()
        if not raw_path:
            self.send_json(400, {"valid": False, "error": "Library path is required"})
            return

        norm_path = os.path.abspath(raw_path)

        forbidden_roots = ["c:/", "c:/windows", "c:/program files", "c:/program files (x86)"]
        if norm_path.lower().replace(os.sep, "/") in forbidden_roots:
            self.send_json(400, {"valid": False, "error": "Cannot attach critical system root as library directory."})
            return

        if not os.path.exists(norm_path) or not os.path.isdir(norm_path):
            self.send_json(200, {"valid": False, "error": "Specified folder does not exist or is not a directory."})
            return

        meta_db = os.path.join(norm_path, "metadata.db")
        if not os.path.isfile(meta_db):
            self.send_json(200, {"valid": False, "error": "metadata.db not found in specified folder. Must be a valid Calibre library."})
            return

        stats = inspect_calibre_library_readonly(norm_path)
        if not stats["db_exists"]:
            self.send_json(200, {"valid": False, "error": "Failed to inspect metadata.db in read-only mode."})
            return

        self.send_json(200, {
            "valid": True,
            "path": norm_path,
            "books_count": stats["books_count"],
            "authors_count": stats["authors_count"],
            "tags_count": stats["tags_count"],
            "series_count": stats["series_count"]
        })

    def handle_setup_complete(self):
        if not CONFIG_MANAGER.is_setup_completed() and not self.is_local_request():
            self.send_json(403, {"success": False, "error": "Setup is only accessible from local server machine (complete)."})
            return
        if CONFIG_MANAGER.is_setup_completed():
            self.send_json(403, {"success": False, "error": "Setup has already been completed. Reconfiguration restricted."})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            req = json.loads(body.decode("utf-8"))
        except Exception:
            self.send_json(400, {"success": False, "error": "Malformed JSON payload"})
            return

        inst = req.get("institution", {})
        admin = req.get("admin", {})
        lib = req.get("library", {})

        inst_name = inst.get("name", "").strip()
        inst_short = inst.get("short_name", "").strip()
        admin_user = admin.get("username", "").strip()
        admin_pass = admin.get("password", "")
        admin_name = admin.get("full_name", "").strip()
        admin_dept = admin.get("department", "").strip()
        lib_path = lib.get("path", "").strip()
        lib_name = lib.get("display_name", "").strip()

        if not inst_name or not inst_short:
            self.send_json(400, {"success": False, "error": "Institution name and short acronym are required."})
            return
        if not admin_user or len(admin_user) < 3:
            self.send_json(400, {"success": False, "error": "Administrator username must be at least 3 characters."})
            return
        if not admin_pass or len(admin_pass) < 8:
            self.send_json(400, {"success": False, "error": "Administrator password must be at least 8 characters long."})
            return
        if not lib_path or not os.path.isfile(os.path.join(lib_path, "metadata.db")):
            self.send_json(400, {"success": False, "error": "Valid Calibre library with metadata.db is required."})
            return

        try:
            existing_users = [u["username"] for u in USER_MANAGER.list_users()]
            if admin_user in existing_users:
                USER_MANAGER.change_password(admin_user, admin_pass, actor="SetupBootstrap")
                USER_MANAGER.update_profile(admin_user, admin_name, role="Administrator", department=admin_dept, actor="SetupBootstrap")
            else:
                USER_MANAGER.add_user(
                    username=admin_user,
                    password=admin_pass,
                    full_name=admin_name,
                    role="Administrator",
                    department=admin_dept,
                    readonly=False,
                    actor="SetupBootstrap"
                )

            CONFIG_MANAGER.update_institution_settings(
                name=inst_name,
                short_name=inst_short,
                library_name=inst.get("library_name", "Digital Library").strip(),
                motto=inst.get("motto", "").strip(),
                contact_email=inst.get("contact_email", "").strip(),
                contact_phone=inst.get("contact_phone", "").strip(),
                logo_url=inst.get("logo_url", "").strip(),
                actor="SetupBootstrap"
            )
            sync_branding_json_file()

            CONFIG_MANAGER.add_library(
                display_name=lib_name or "Main Academic Collection",
                path=os.path.abspath(lib_path),
                is_default=True,
                is_active=True,
                actor="SetupBootstrap"
            )
            sync_desktop_library_pref(lib_path)

            CONFIG_MANAGER.set_setup_completed(True, actor="SetupBootstrap")
            try:
                BACKEND_SUPERVISOR.sync_libraries()
            except Exception as sync_err:
                logger.warning("Backend library sync notice: %s", sync_err)

            self.send_json(200, {"success": True, "redirect": "/admin"})
        except Exception as e:
            self.send_json(500, {"success": False, "error": f"Failed to complete setup: {e}"})

    # ==============================================================================
    # Administration Portal Handlers (Admin Console V2)
    # ==============================================================================
    def serve_admin_page(self):
        token = self.get_session_token()
        session = get_session(token)
        if not session:
            self._redirect_to_login()
            return

        if session.get("role") != "Administrator":
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>403 Forbidden</h1><p>Institutional Administrator privileges required to access administration portal.</p>")
            return

        admin_v2_file = os.path.join(TEMPLATES_DIR, "admin_v2.html")
        admin_file = admin_v2_file if os.path.exists(admin_v2_file) else os.path.join(TEMPLATES_DIR, "admin.html")
        if not os.path.exists(admin_file):
            self.send_error(500, "Admin template missing")
            return
        with open(admin_file, "r", encoding="utf-8") as f:
            html_text = f.read()

        inst = CONFIG_MANAGER.get_institution_settings()
        inst_name = inst.get("name") or inst.get("institution_name") or "Institutional Digital Library"
        inst_short = inst.get("short_name") or "IDL"
        disp_name = session.get("displayName") or session.get("username") or "Administrator"
        if disp_name == "Aethelgard Institute of Technology Administrator" and inst_name != "Aethelgard Institute of Technology":
            disp_name = f"{inst_name} Administrator"
        u_role = session.get("role") or "Administrator"

        html_text = html_text.replace("{{INSTITUTION_NAME}}", html.escape(inst_name))
        html_text = html_text.replace("{{INSTITUTION_SHORT_NAME}}", html.escape(inst_short))
        html_text = html_text.replace("{{ADMIN_DISPLAY_NAME}}", html.escape(disp_name))
        html_text = html_text.replace("{{ADMIN_ROLE}}", html.escape(u_role))
        content = html_text.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        apply_no_cache_headers(self)
        self.end_headers()
        self.wfile.write(content)

    def handle_admin_dashboard(self, session=None):
        inst = CONFIG_MANAGER.get_institution_settings()
        libs = self.get_enriched_libraries()
        users = USER_MANAGER.list_users()
        recent_audit = CONFIG_MANAGER.get_audit_log(limit=8)
        backups = CONFIG_MANAGER.list_backups()
        backend_online = BACKEND_SUPERVISOR.is_backend_responsive()

        with SESSION_LOCK:
            active_sessions = len(SESSIONS)

        current_user = {}
        if session:
            uname = session.get("username", "admin")
            prof = CONFIG_MANAGER.get_user_profile(uname)
            disp = prof.get("display_name") or session.get("displayName") or uname
            inst_name = inst.get("name") or inst.get("institution_name") or ""
            if disp == "Aethelgard Institute of Technology Administrator" and inst_name and inst_name != "Aethelgard Institute of Technology":
                disp = f"{inst_name} Administrator"
            current_user = {
                "username": uname,
                "displayName": disp,
                "role": prof.get("role") or session.get("role", "Administrator"),
                "department": prof.get("department", "")
            }

        data = {
            "institution": inst,
            "current_user": current_user,
            "libraries": libs,
            "users_count": len(users),
            "active_users_count": sum(1 for u in users if u.get("is_active", True)),
            "active_sessions_count": active_sessions,
            "recent_audit": recent_audit,
            "backups": backups,
            "backups_count": len(backups),
            "last_backup": backups[0]["created_at"] if backups else "No snapshots yet",
            "catalogue_settings": CONFIG_MANAGER.get_catalogue_settings(),
            "landing_content": CONFIG_MANAGER.get_landing_page_content(),
            "system": {
                "gateway_host": HOST,
                "gateway_port": PORT,
                "calibre_port": _backend_address.port or 8088,
                "total_books": sum(int(l.get("books_count", 0) or 0) for l in libs if l.get("is_active", 1)),
                "active_sessions": active_sessions,
                "storage_mode": "SQLite (AppData Managed)",
                "calibre_backend_online": backend_online,
                "branding_dir": CONFIG_MANAGER.get_branding_directory(),
                "backups_dir": CONFIG_MANAGER.get_backups_directory()
            }
        }
        self.send_json(200, data)

    def handle_admin_system(self):
        backend_online = BACKEND_SUPERVISOR.is_backend_responsive()

        lan_ips = []
        try:
            hostname = socket.gethostname()
            _, _, ips = socket.gethostbyname_ex(hostname)
            lan_ips = [ip for ip in ips if not ip.startswith("127.")]
        except Exception:
            lan_ips = ["127.0.0.1"]

        with SESSION_LOCK:
            active_sessions = len(SESSIONS)

        data = {
            "gateway_host": HOST,
            "gateway_port": PORT,
            "calibre_port": _backend_address.port or 8088,
            "calibre_backend_online": backend_online,
            "calibre_bin": USER_MANAGER.calibre_bin,
            "lan_ips": lan_ips,
            "db_path": CONFIG_MANAGER.db_path,
            "userdb_path": USER_MANAGER.userdb_path,
            "branding_dir": CONFIG_MANAGER.get_branding_directory(),
            "backups_dir": CONFIG_MANAGER.get_backups_directory(),
            "session_timeout_seconds": SESSION_TIMEOUT,
            "active_sessions_count": active_sessions,
            "storage_mode": "Isolated Development Override" if os.environ.get("CALIBRE_INSTITUTIONAL_CONFIG_DIR") else "Windows AppData",
            "setup_completed": CONFIG_MANAGER.is_setup_completed()
        }
        self.send_json(200, data)

    def handle_admin_posts(self, path, session):
        actor = session.get("username", "Admin")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            req = json.loads(body.decode("utf-8"))
        except Exception:
            req = {}

        # 1. Update Institution Settings & Branding
        if path == "/api/admin/settings":
            try:
                name = req.get("name", "").strip() or None
                short_name = req.get("short_name", "").strip() or None
                library_name = req.get("library_name", "").strip() or None
                motto = req.get("motto", "").strip() if "motto" in req else None
                contact_email = req.get("contact_email", "").strip() if "contact_email" in req else None
                contact_phone = req.get("contact_phone", "").strip() if "contact_phone" in req else None
                logo_url = req.get("logo_url", "").strip() if "logo_url" in req else None
                primary_color = req.get("primary_color", "").strip() or None
                accent_gold = req.get("accent_gold", "").strip() or None

                CONFIG_MANAGER.update_institution_settings(
                    name=name,
                    short_name=short_name,
                    library_name=library_name,
                    motto=motto,
                    contact_email=contact_email,
                    contact_phone=contact_phone,
                    logo_url=logo_url,
                    primary_color=primary_color,
                    accent_gold=accent_gold,
                    actor=actor
                )
                sync_branding_json_file()
                self.send_json(200, {"success": True, "settings": CONFIG_MANAGER.get_institution_settings()})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 1c. Landing Page Content Management API
        if path == "/api/admin/landing-content":
            try:
                content = CONFIG_MANAGER.update_landing_page_content(req, actor=session.get("username", "Administrator"))
                self.send_json(200, {"success": True, "content": content})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 1d. Reset Landing Page Content to Defaults
        if path == "/api/admin/landing-content/reset":
            try:
                content = CONFIG_MANAGER.reset_landing_page_content(actor=session.get("username", "Administrator"))
                self.send_json(200, {"success": True, "content": content})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 1e. Upload Landing Page Image into Writable AppData Directory
        if path == "/api/admin/landing-content/upload-image":
            try:
                filename = os.path.basename(req.get("filename", "landing-image.png"))
                data_url = req.get("data_url", "")
                if "," not in data_url:
                    self.send_json(400, {"success": False, "error": "Invalid image data payload."})
                    return
                _, b64data = data_url.split(",", 1)
                raw_bytes = base64.b64decode(b64data)
                if len(raw_bytes) > 10 * 1024 * 1024:
                    self.send_json(413, {"success": False, "error": "Image file exceeds 10 MB limit."})
                    return

                ext = os.path.splitext(filename)[1].lower()
                if ext not in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
                    self.send_json(400, {"success": False, "error": "Unsupported image format. Use PNG, JPG, WEBP, or SVG."})
                    return

                safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", os.path.splitext(filename)[0]).strip("_") or "landing"
                safe_name = f"landing_{safe_stem}_{int(time.time())}{ext}"
                branding_dir = CONFIG_MANAGER.get_branding_directory()
                target_path = os.path.abspath(os.path.join(branding_dir, safe_name))

                if "program files" in target_path.lower():
                    self.send_json(403, {"success": False, "error": "Writing assets to Program Files is strictly prohibited."})
                    return

                with open(target_path, "wb") as f:
                    f.write(raw_bytes)

                public_url = f"/branding-assets/{safe_name}"
                self.send_json(200, {
                    "success": True,
                    "image_url": public_url,
                    "filename": safe_name
                })
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 1b. Upload Custom Logo into Writable AppData Branding Directory
        if path == "/api/v2/admin/branding/upload-logo":
            try:
                filename = os.path.basename(req.get("filename", "institution-emblem.svg"))
                data_url = req.get("data_url", "")
                if "," not in data_url:
                    self.send_json(400, {"success": False, "error": "Invalid logo data payload."})
                    return
                _, b64data = data_url.split(",", 1)
                raw_bytes = base64.b64decode(b64data)
                if len(raw_bytes) > 5 * 1024 * 1024:
                    self.send_json(413, {"success": False, "error": "Logo file exceeds 5 MB limit."})
                    return

                ext = os.path.splitext(filename)[1].lower()
                if ext not in (".svg", ".png", ".jpg", ".jpeg", ".webp"):
                    self.send_json(400, {"success": False, "error": "Unsupported logo file extension. Use SVG, PNG, JPG, or WEBP."})
                    return

                safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", os.path.splitext(filename)[0]).strip("_") or "emblem"
                safe_name = f"{safe_stem}{ext}"
                branding_dir = CONFIG_MANAGER.get_branding_directory()
                target_path = os.path.abspath(os.path.join(branding_dir, safe_name))

                # Critical Engineering Safeguard: Never write inside Program Files
                if "program files" in target_path.lower():
                    self.send_json(403, {"success": False, "error": "Writing logos to Program Files is strictly prohibited."})
                    return

                with open(target_path, "wb") as f:
                    f.write(raw_bytes)

                logo_url = f"/branding-assets/{safe_name}"
                CONFIG_MANAGER.update_institution_settings(logo_url=logo_url, actor=actor)
                sync_branding_json_file()
                CONFIG_MANAGER.log_audit(actor, "BRANDING_LOGO_UPLOADED", json.dumps({
                    "filename": safe_name,
                    "logo_url": logo_url,
                    "disk_path": target_path
                }))
                self.send_json(200, {
                    "success": True,
                    "logo_url": logo_url,
                    "disk_path": target_path
                })
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 1c. Update Catalogue & Metadata Settings
        if path == "/api/admin/catalogue-settings":
            try:
                updated = CONFIG_MANAGER.update_catalogue_settings(
                    page_size=req.get("page_size", 24),
                    default_sort=req.get("default_sort", "title_asc"),
                    facets=req.get("facets") if req.get("facets") is not None else req.get("exposed_facets"),
                    inject_bar=bool(req.get("inject_bar", True)),
                    inbrowser_reader=bool(req.get("inbrowser_reader", True)),
                    download_policy=req.get("download_policy", "authenticated"),
                    actor=actor
                )
                self.send_json(200, {"success": True, "catalogue_settings": updated})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 2. Add Library
        if path == "/api/admin/libraries":
            label = req.get("display_name", "").strip()
            lib_path = req.get("library_path", "").strip()
            is_def = bool(req.get("is_default", False))
            policy = req.get("access_policy", "public").strip() or "public"

            if not lib_path or not os.path.isfile(os.path.join(lib_path, "metadata.db")):
                self.send_json(400, {"success": False, "error": "metadata.db not found in specified directory."})
                return

            try:
                lib = CONFIG_MANAGER.add_library(
                    display_name=label or os.path.basename(lib_path),
                    path=os.path.abspath(lib_path),
                    is_default=is_def,
                    is_active=True,
                    access_policy=policy,
                    actor=actor
                )
                if is_def:
                    sync_desktop_library_pref(lib_path)
                try:
                    BACKEND_SUPERVISOR.sync_libraries()
                except Exception as ex:
                    logger.warning("Backend synchronization notice: %s", ex)
                self.send_json(200, {"success": True, "library": lib, "library_id": lib["library_id"]})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 3. Set Default Library
        if path == "/api/admin/libraries/default":
            lib_id = req.get("library_id") or req.get("id")
            if not lib_id:
                self.send_json(400, {"success": False, "error": "library_id required"})
                return
            CONFIG_MANAGER.update_library(lib_id, is_default=True, is_active=True, actor=actor)
            lib = CONFIG_MANAGER.get_library(lib_id)
            if lib and lib.get("path"):
                sync_desktop_library_pref(lib["path"])
            try:
                BACKEND_SUPERVISOR.sync_libraries()
            except Exception as ex:
                logger.warning("Backend synchronization notice: %s", ex)
            self.send_json(200, {"success": True})
            return

        # 3b. Update Library Access Policy
        if path == "/api/v2/admin/libraries/policy":
            lib_id = req.get("library_id") or req.get("id")
            policy = req.get("access_policy", "public")
            if not lib_id:
                self.send_json(400, {"success": False, "error": "library_id required"})
                return
            CONFIG_MANAGER.update_library(lib_id, access_policy=policy, actor=actor)
            self.send_json(200, {"success": True})
            return

        # 4. Toggle Library Active
        if path == "/api/admin/libraries/toggle":
            lib_id = req.get("library_id") or req.get("id")
            is_active = bool(req.get("is_active", True))
            CONFIG_MANAGER.update_library(lib_id, is_active=is_active, actor=actor)
            try:
                BACKEND_SUPERVISOR.sync_libraries()
            except Exception as ex:
                logger.warning("Backend synchronization notice: %s", ex)
            self.send_json(200, {"success": True})
            return

        # 5. Remove Library
        if path == "/api/admin/libraries/remove":
            lib_id = req.get("library_id") or req.get("id")
            CONFIG_MANAGER.remove_library(lib_id, actor=actor)
            try:
                BACKEND_SUPERVISOR.sync_libraries()
            except Exception as ex:
                logger.warning("Backend synchronization notice: %s", ex)
            self.send_json(200, {"success": True})
            return

        # 6. Create User
        if path == "/api/admin/users/create":
            u = req.get("username", "").strip()
            p = req.get("password", "")
            fn = req.get("full_name", "").strip()
            r = req.get("role", "Patron")
            dept = req.get("department", "").strip()
            ro = bool(req.get("readonly", False))
            allowed_libs = req.get("allowed_libraries", "*")
            if isinstance(allowed_libs, list):
                allowed_libs = ",".join(str(x).strip() for x in allowed_libs if str(x).strip()) or "*"

            try:
                res = USER_MANAGER.add_user(
                    username=u,
                    password=p,
                    full_name=fn,
                    role=r,
                    department=dept,
                    readonly=ro,
                    allowed_libraries=allowed_libs,
                    actor=actor
                )
                self.send_json(200, {"success": True, "user": res})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 7. Change Password
        if path == "/api/admin/users/change-password":
            u = req.get("username", "").strip()
            np = req.get("new_password", "")
            try:
                USER_MANAGER.change_password(u, np, actor=actor)
                revoke_user_sessions(u)
                self.send_json(200, {"success": True})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 8. Set Readonly
        if path == "/api/admin/users/readonly":
            u = req.get("username", "").strip()
            ro = bool(req.get("readonly", False))
            try:
                USER_MANAGER.set_readonly(u, ro, actor=actor)
                revoke_user_sessions(u)
                self.send_json(200, {"success": True})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 8b. Update Profile & Library Access Scope
        if path == '/api/admin/users/profile':
            u = req.get('username', '').strip()
            allowed_libs = req.get('allowed_libraries')
            if isinstance(allowed_libs, list):
                allowed_libs = ",".join(str(x).strip() for x in allowed_libs if str(x).strip()) or "*"
            is_act = req.get('is_active')
            if is_act is False and u == actor:
                self.send_json(400, {'success': False, 'error': 'Cannot deactivate currently logged-in administrator account.'})
                return
            USER_MANAGER.update_profile(
                u,
                req.get('full_name', ''),
                req.get('role', 'Patron'),
                req.get('department', ''),
                is_active=is_act,
                allowed_libraries=allowed_libs,
                actor=actor
            )
            revoke_user_sessions(u)
            self.send_json(200, {'success': True})
            return

        # 8c. Activate / Deactivate Account
        if path == "/api/admin/users/status":
            u = req.get("username", "").strip()
            is_active = bool(req.get("is_active", True))
            if not is_active and u == actor:
                self.send_json(400, {"success": False, "error": "Cannot deactivate currently logged-in administrator account."})
                return
            CONFIG_MANAGER.set_user_active(u, is_active=is_active, actor=actor)
            if not is_active:
                revoke_user_sessions(u)
            self.send_json(200, {"success": True, "username": u, "is_active": is_active})
            return

        # 9. Remove User (guards against self-deletion)
        if path == "/api/admin/users/remove":
            u = req.get("username", "").strip()
            if u == actor:
                self.send_json(400, {"success": False, "error": "Cannot delete currently logged-in administrator account."})
                return
            try:
                USER_MANAGER.remove_user(u, actor=actor)
                CONFIG_MANAGER.delete_user_profile(u, actor=actor)
                revoke_user_sessions(u)
                self.send_json(200, {"success": True})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 10. Backup Database (Legacy V1 + V2 Tiered Backups)
        if path == "/api/admin/system/backup":
            try:
                bp = CONFIG_MANAGER.create_backup()
                CONFIG_MANAGER.log_audit(actor, "BACKUP_TIER1_CONFIG_CREATED", json.dumps({"backup_path": bp}))
                self.send_json(200, {"success": True, "backup_path": bp})
            except Exception as e:
                self.send_json(500, {"success": False, "error": str(e)})
            return

        if path == "/api/v2/admin/backups/create":
            try:
                tier = req.get("tier", "config")
                lib_id = req.get("library_id")
                res = CONFIG_MANAGER.create_tier_backup(
                    tier=tier,
                    userdb_path=USER_MANAGER.userdb_path,
                    library_id=lib_id,
                    actor=actor
                )
                self.send_json(200, res)
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        if path == "/api/v2/admin/backups/verify":
            try:
                fname = req.get("filename", "")
                res = CONFIG_MANAGER.verify_backup(fname)
                self.send_json(200, {
                    "success": bool(res.get("valid")),
                    "verified": bool(res.get("valid")),
                    "sha256": res.get("sha256", ""),
                    "verified_files": res.get("files_count"),
                    "tier_label": res.get("integrity", "ok"),
                    "verification": res
                })
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        if path == "/api/v2/admin/backups/restore":
            try:
                fname = req.get("filename", "")
                target_lib_dir = req.get("target_library_dir")
                res = CONFIG_MANAGER.restore_backup(
                    filename=fname,
                    userdb_path=USER_MANAGER.userdb_path,
                    target_library_dir=target_lib_dir,
                    actor=actor
                )
                if res.get("tier") == "config":
                    sync_branding_json_file()
                res["restored_tier"] = res.get("tier", "snapshot")
                res["target_path"] = res.get("destination") or (CONFIG_MANAGER.db_path if res.get("tier") == "config" else USER_MANAGER.userdb_path)
                self.send_json(200, res)
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        if path == "/api/v2/admin/network":
            try:
                global SESSION_TIMEOUT
                ttl = int(req.get("session_timeout_seconds", SESSION_TIMEOUT) or 28800)
                SESSION_TIMEOUT = max(300, min(86400, ttl))
                bind_mode = str(req.get("bind_mode", "127.0.0.1") or "127.0.0.1")
                tls_mode = str(req.get("tls_mode", "local") or "local")
                CONFIG_MANAGER.set_config_value("session_timeout_seconds", str(SESSION_TIMEOUT), actor=actor)
                CONFIG_MANAGER.set_config_value("network_bind_mode", bind_mode, actor=actor)
                CONFIG_MANAGER.set_config_value("network_tls_mode", tls_mode, actor=actor)
                target_bind = "0.0.0.0" if bind_mode in ("custom_lan", "0.0.0.0", "all") else "127.0.0.1"
                CONFIG["gateway_host"] = target_bind
                try:
                    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                        json.dump(CONFIG, f, indent=2)
                except Exception:
                    pass
                self.send_json(200, {
                    "success": True,
                    "session_timeout_seconds": SESSION_TIMEOUT,
                    "bind_mode": bind_mode,
                    "tls_mode": tls_mode,
                    "gateway_host": target_bind,
                    "gateway_port": PORT
                })
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 11. Reload / Shutdown
        if path == '/api/admin/system/shutdown':
            self.send_json(200, {'success': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        if path == "/api/admin/system/reload":
            ready = BACKEND_SUPERVISOR.restart_backend()
            self.send_json(200 if ready else 503, {"success": ready})
            return

        self.send_error(404, "Unknown Admin Action")

    # ==============================================================================
    # Dynamic Landing Page & Static Assets
    # ==============================================================================
    def serve_landing_page(self):
        index_file = os.path.join(TEMPLATES_DIR, "index.html")
        if not os.path.exists(index_file):
            self.send_error(500, "Landing page template missing")
            return
        with open(index_file, "r", encoding="utf-8") as f:
            template = f.read()

        inst = CONFIG_MANAGER.get_institution_settings()
        branding_path = os.environ.get('CALIBRE_INSTITUTIONAL_BRANDING')
        brand = {}
        if branding_path and os.path.isfile(branding_path):
            try:
                with open(branding_path, encoding='utf-8') as stream:
                    brand = json.load(stream)
            except Exception:
                brand = {}

        # Prioritize ConfigManager values updated via Admin Console, falling back to branding.json
        name_val = inst.get("name") or inst.get("institution_name") or brand.get('institution_name') or "Aethelgard Institute of Technology"
        short_val = inst.get("short_name") or brand.get('short_name') or "AIT"
        lib_val = inst.get("library_name") or inst.get("library_title") or brand.get('library_title') or "Institutional Digital Library & Research Repository"
        motto_val = inst.get("motto") or brand.get('motto') or "Academic Volumes, Digital Collections & Faculty Research"
        logo_val = inst.get('logo_path') or brand.get('logo_url') or '/static/images/institution-mark.svg'
        primary_color = inst.get('primary_color') or brand.get('primary_color') or '#183c34'

        content_settings = CONFIG_MANAGER.get_landing_page_content()

        rendered = template.replace("{{INSTITUTION_NAME}}", html.escape(name_val))
        rendered = rendered.replace("{{INSTITUTION_SHORT_NAME}}", html.escape(short_val))
        rendered = rendered.replace("{{LIBRARY_DISPLAY_NAME}}", html.escape(lib_val))
        rendered = rendered.replace("{{INSTITUTION_MOTTO}}", html.escape(motto_val))
        rendered = rendered.replace("{{LOGO_URL}}", html.escape(logo_val, quote=True))
        rendered = rendered.replace("{{PRIMARY_COLOR}}", html.escape(primary_color))
        rendered = rendered.replace("{{CONTACT_EMAIL}}", html.escape(inst.get("contact_email") or f"library@{short_val.lower()}.edu"))
        rendered = rendered.replace("{{CONTACT_PHONE}}", html.escape(inst.get("contact_phone") or ""))

        # Dynamic Landing Page Copy & Images
        rendered = rendered.replace("{{HERO_EYEBROW}}", html.escape(content_settings.get("hero_eyebrow") or "A HOME FOR CURIOUS MINDS"))
        rendered = rendered.replace("{{HERO_TITLE}}", content_settings.get("hero_title") or "Great ideas<br>begin with<br><em>an open book.</em>")
        rendered = rendered.replace("{{HERO_DESCRIPTION}}", html.escape(content_settings.get("hero_description") or "Discover academic works, explore new perspectives, and make room for your next breakthrough. Your institutional collection, wherever you learn."))
        rendered = rendered.replace("{{CTA_LABEL}}", html.escape(content_settings.get("cta_label") or "Explore the library ↗"))
        rendered = rendered.replace("{{ABOUT_HEADING}}", content_settings.get("about_heading") or "A collection that<br>moves you forward.")
        rendered = rendered.replace("{{ABOUT_DESCRIPTION}}", html.escape(content_settings.get("about_description") or "From foundational texts to fresh thinking, find the resources that support your studies, teaching, and research."))
        rendered = rendered.replace("{{FOOTER_TEXT}}", html.escape(content_settings.get("footer_text") or "Powered by Calibre · Built for our community"))

        content = rendered.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        apply_no_cache_headers(self)
        self.end_headers()
        self.wfile.write(content)

    def serve_branding_asset(self, path, head_only=False):
        rel = os.path.basename(path[len("/branding-assets/"):].lstrip("/\\"))
        branding_dir = os.path.realpath(CONFIG_MANAGER.get_branding_directory())
        target_path = os.path.realpath(os.path.join(branding_dir, rel))
        try:
            if os.path.commonpath([branding_dir, target_path]) != branding_dir:
                self.send_error(403, "Access Denied")
                return
        except ValueError:
            self.send_error(403, "Access Denied")
            return

        if not os.path.isfile(target_path):
            self.send_error(404, "Branding asset not found")
            return

        mime_type, _ = mimetypes.guess_type(target_path)
        with open(target_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime_type or "image/svg+xml")
        self.send_header("Content-Length", str(len(content)))
        apply_no_cache_headers(self)
        self.end_headers()
        if not head_only:
            self.wfile.write(content)

    def serve_static(self, path, head_only=False):
        relpath = path[len("/static/"):].lstrip("/\\")
        normalized_relpath = os.path.normpath(relpath.replace("/", os.sep).replace("\\", os.sep))

        canonical_static = os.path.realpath(STATIC_DIR)
        target_path = os.path.realpath(os.path.join(canonical_static, normalized_relpath))

        try:
            if os.path.commonpath([canonical_static, target_path]) != canonical_static:
                self.send_error(403, "Access Denied: Path Traversal Prohibited")
                return
        except ValueError:
            self.send_error(403, "Access Denied: Path Traversal Prohibited")
            return

        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            self.send_error(404, "Static file not found")
            return

        mime_type, _ = mimetypes.guess_type(target_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        try:
            with open(target_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            if not head_only:
                self.wfile.write(content)
        except Exception as e:
            print(f"[Gateway Error] Error serving static asset: {e}")
            self.send_error(500, "Error loading asset")

    def serve_catalog(self, query=None):
        token = self.get_session_token()
        session = get_session(token)
        if not session:
            self.send_json(401, {"error": "Authentication required. Please sign in with your institutional credentials to browse repository volumes."})
            return

        req_lib = (query or {}).get("library_id", [""])[0]
        if not CONFIG_MANAGER.is_user_allowed_library(session["username"], session["role"], req_lib):
            self.send_json(403, {"error": "Access restricted: Your institutional account does not have permission for this repository collection."})
            return

        url = f"{BACKEND_URL}/ajax/books"
        if req_lib:
            url = f"{BACKEND_URL}/ajax/books/{urllib.parse.quote(req_lib)}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {session['basic_auth']}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            books = []
            if isinstance(data, dict):
                for bid, binfo in data.items():
                    if isinstance(binfo, dict):
                        books.append({
                            "id": binfo.get("application_id", bid),
                            "title": binfo.get("title", "Untitled"),
                            "author": ", ".join(binfo.get("authors", ["Unknown"])),
                            "description": binfo.get("comments") or "Authoritative institutional repository publication.",
                            "formats": binfo.get("formats", ["epub"])
                        })
            if not books:
                # Direct metadata.db read fallback if Content Server returns empty or during bootstrap
                active_libs = CONFIG_MANAGER.get_libraries()
                # Check requested library first, or all active libraries
                target_libs = [l for l in active_libs if (not req_lib or str(l.get("id")) == str(req_lib) or l.get("display_name") == req_lib or l.get("library_id") == req_lib)]
                if not target_libs:
                    target_libs = active_libs
                for l in target_libs:
                    lpath = l.get("path")
                    if lpath and os.path.isfile(os.path.join(lpath, "metadata.db")):
                        try:
                            import sqlite3
                            with sqlite3.connect(f"file:{os.path.join(lpath, 'metadata.db')}?mode=ro", uri=True) as lconn:
                                cur = lconn.cursor()
                                cur.execute("SELECT id, title, author_sort FROM books ORDER BY id ASC")
                                for r in cur.fetchall():
                                    books.append({
                                        "id": r[0],
                                        "title": r[1],
                                        "author": r[2] or "Unknown",
                                        "description": "Authoritative institutional repository publication.",
                                        "formats": ["pdf"]
                                    })
                        except Exception:
                            pass
            self.send_json(200, books)
        except urllib.error.HTTPError as he:
            if he.code in (401, 403):
                self.send_json(403, {"error": "Access restricted: Your institutional account does not have permission for this repository collection."})
            else:
                self.send_json(503, {"error": "Institutional repository service is temporarily unavailable."})
        except Exception as e:
            print(f"[Gateway Error] Upstream catalog error: {e}")
            # Resilient fallback: read from metadata.db directly
            books = []
            try:
                active_libs = CONFIG_MANAGER.get_libraries()
                target_libs = [l for l in active_libs if (not req_lib or str(l.get("id")) == str(req_lib) or l.get("display_name") == req_lib or l.get("library_id") == req_lib)]
                if not target_libs:
                    target_libs = active_libs
                for l in target_libs:
                    lpath = l.get("path")
                    if lpath and os.path.isfile(os.path.join(lpath, "metadata.db")):
                        import sqlite3
                        with sqlite3.connect(f"file:{os.path.join(lpath, 'metadata.db')}?mode=ro", uri=True) as lconn:
                            cur = lconn.cursor()
                            cur.execute("SELECT id, title, author_sort FROM books ORDER BY id ASC")
                            for r in cur.fetchall():
                                books.append({
                                    "id": r[0],
                                    "title": r[1],
                                    "author": r[2] or "Unknown",
                                    "description": "Authoritative institutional repository publication.",
                                    "formats": ["pdf"]
                                })
            except Exception as dbe:
                print(f"[Gateway Error] Direct metadata.db fallback error: {dbe}")
            if books:
                self.send_json(200, books)
            else:
                self.send_json(503, {"error": "Institutional repository service is temporarily unavailable."})

    def _extract_requested_calibre_library(self, parsed_path: str, query_dict: dict) -> str:
        """Extracts target library_id from /calibre/* URL query or path segments."""
        if "library_id" in query_dict and query_dict["library_id"]:
            return query_dict["library_id"][0]
        parts = [p for p in parsed_path.split("/") if p]
        # e.g. ['calibre', 'ajax', 'books', '<library_id>'] or ['calibre', 'get', '<what>', '<book_id>', '<library_id>']
        if len(parts) >= 4 and parts[1] == "ajax" and parts[2] in ("books", "categories", "search"):
            return urllib.parse.unquote(parts[3])
        if len(parts) >= 5 and parts[1] == "ajax" and parts[2] == "book":
            return urllib.parse.unquote(parts[4])
        if len(parts) >= 5 and parts[1] == "get":
            return urllib.parse.unquote(parts[4])
        return ""

    # ==============================================================================
    # Branded Institutional PDF Reader & Secure PDF Delivery Endpoints
    # ==============================================================================
    def _get_active_reader_session(self):
        token = self.get_session_token()
        session = get_session(token)
        if not session:
            return None, 401, "Authentication required. Please sign in to access this publication."
        prof = CONFIG_MANAGER.get_user_profile(session["username"])
        if not prof.get("is_active", True):
            destroy_session(token)
            return None, 403, "This institutional account has been deactivated."
        return session, 200, None

    def _redirect_to_login(self, next_path=None):
        if not next_path:
            next_path = self.path
        # Sanitize next_path to internal allowlist to prevent open redirects
        target_path = "/"
        if next_path and next_path.startswith("/") and not next_path.startswith("//") and not next_path.startswith("/\\"):
            # Ensure it is a recognized internal path
            if (next_path.startswith("/calibre") or next_path.startswith("/reader") or
                next_path.startswith("/admin")):
                target_path = next_path
        if target_path and target_path != "/":
            loc = f"/?login_required=1&next={urllib.parse.quote(target_path)}"
        else:
            loc = "/?login_required=1"
        self.send_response(302)
        self.send_header("Location", loc)
        apply_no_cache_headers(self)
        self.end_headers()

    def serve_reader_page(self, head_only=False):
        session, code, err = self._get_active_reader_session()
        if not session:
            self._redirect_to_login()
            return

        reader_file = os.path.join(TEMPLATES_DIR, "reader.html")
        if not os.path.isfile(reader_file):
            self.send_safe_error(500, "Reader template missing")
            return

        with open(reader_file, "r", encoding="utf-8") as f:
            template = f.read()

        inst = CONFIG_MANAGER.get_institution_settings()
        name_val = inst.get("name") or inst.get("institution_name") or "Institutional Digital Library"
        short_val = inst.get("short_name") or "IDL"
        logo_val = inst.get("logo_path") or "/static/images/institution-mark.svg"
        primary_color = inst.get("primary_color") or "#183c34"

        rendered = template.replace("{{INSTITUTION_NAME}}", html.escape(name_val))
        rendered = rendered.replace("{{INSTITUTION_SHORT_NAME}}", html.escape(short_val))
        rendered = rendered.replace("{{LOGO_URL}}", html.escape(logo_val, quote=True))
        rendered = rendered.replace("{{PRIMARY_COLOR}}", html.escape(primary_color))

        content = rendered.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        if not head_only:
            self.wfile.write(content)

    def _resolve_authorized_book_pdf(self, session: dict, query: dict) -> tuple:
        """
        Safely resolves and validates an authorized book PDF from Calibre metadata.db.
        Never accepts filesystem paths from request parameters.
        Returns (meta_dict, status_code, error_msg).
        """
        raw_bid = (query.get("book_id") or [""])[0].strip()
        if not raw_bid or not raw_bid.isdigit() or int(raw_bid) <= 0:
            return None, 400, "Invalid book_id parameter: must be a positive integer."
        book_id = int(raw_bid)

        raw_lib = (query.get("library_id") or [""])[0].strip()
        active_libs = CONFIG_MANAGER.get_active_libraries()
        if not active_libs:
            return None, 404, "No active Calibre libraries are configured."

        target_lib = None
        if raw_lib:
            req_norm = raw_lib.strip().lower()
            for lib in active_libs:
                lid = lib.get("library_id", "").lower()
                bname = os.path.basename(lib.get("path", "")).replace(" ", "_").lower()
                dname = lib.get("display_name", "").replace(" ", "_").lower()
                if req_norm in (lid, bname, dname):
                    target_lib = lib
                    break
            if not target_lib:
                # Check if it's an inactive or restricted library in full list
                all_libs = CONFIG_MANAGER.get_libraries()
                for lib in all_libs:
                    lid = lib.get("library_id", "").lower()
                    bname = os.path.basename(lib.get("path", "")).replace(" ", "_").lower()
                    if req_norm in (lid, bname):
                        if not CONFIG_MANAGER.is_user_allowed_library(session["username"], session["role"], lib["library_id"]):
                            return None, 403, "Access restricted: Your institutional account does not have permission for this library collection."
                        break
                return None, 404, "Requested library collection was not found."
        else:
            target_lib = next((l for l in active_libs if l.get("is_default")), active_libs[0])

        if not CONFIG_MANAGER.is_user_allowed_library(session["username"], session["role"], target_lib["library_id"]):
            return None, 403, "Access restricted: Your institutional role or account scope does not permit access to this library collection."

        lib_root = os.path.realpath(target_lib.get("path", ""))
        meta_db = os.path.join(lib_root, "metadata.db")
        if not os.path.isfile(meta_db):
            return None, 404, "Library metadata database is unavailable."

        try:
            conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True, timeout=3.0)
            row = conn.execute(
                "SELECT id, title, author_sort, pubdate, path FROM books WHERE id = ?",
                (book_id,)
            ).fetchone()
            if not row:
                conn.close()
                return None, 404, "Requested publication was not found in this library."

            _, title, author_sort, pubdate, rel_book_path = row

            authors_rows = conn.execute(
                "SELECT a.name FROM authors a JOIN books_authors_link l ON a.id = l.author WHERE l.book = ? ORDER BY l.id",
                (book_id,)
            ).fetchall()
            authors = [r[0].replace("|", ", ") for r in authors_rows] if authors_rows else ([author_sort] if author_sort else [])

            pub_row = conn.execute(
                "SELECT p.name FROM publishers p JOIN books_publishers_link l ON p.id = l.publisher WHERE l.book = ?",
                (book_id,)
            ).fetchone()
            publisher = pub_row[0] if pub_row else ""

            fmt_rows = conn.execute(
                "SELECT format, name, uncompressed_size FROM data WHERE book = ?",
                (book_id,)
            ).fetchall()
            conn.close()
        except Exception as ex:
            logger.error("Error reading metadata.db for reader: %s", ex)
            return None, 500, "Failed to read library catalogue metadata."

        pdf_entry = next((r for r in fmt_rows if str(r[0]).upper() == "PDF"), None)
        if not pdf_entry:
            return None, 404, "PDF format is not available for this publication."

        _, pdf_basename, _ = pdf_entry
        candidate_pdf = os.path.realpath(os.path.join(lib_root, rel_book_path, f"{pdf_basename}.pdf"))
        try:
            if os.path.commonpath([lib_root, candidate_pdf]) != lib_root:
                return None, 403, "Access Denied: Invalid file path resolution."
        except ValueError:
            return None, 403, "Access Denied: Invalid file path resolution."

        if not os.path.isfile(candidate_pdf):
            # Case-insensitive fallback inside the book folder
            book_dir = os.path.realpath(os.path.join(lib_root, rel_book_path))
            found_pdf = ""
            if os.path.isdir(book_dir) and os.path.commonpath([lib_root, book_dir]) == lib_root:
                for fn in os.listdir(book_dir):
                    if fn.lower().endswith(".pdf"):
                        cand = os.path.realpath(os.path.join(book_dir, fn))
                        if os.path.isfile(cand) and os.path.commonpath([lib_root, cand]) == lib_root:
                            found_pdf = cand
                            break
            if not found_pdf:
                return None, 404, "The PDF file for this record is missing on disk."
            candidate_pdf = found_pdf

        valid_pdf, page_count, pdf_err = inspect_pdf_document(candidate_pdf)
        if not valid_pdf:
            return None, 422, pdf_err or "The PDF file for this publication is corrupt or unreadable."

        pub_str = str(pubdate or "")
        year = pub_str[:4] if pub_str[:4].isdigit() and int(pub_str[:4]) > 1010 else ""
        cat_settings = CONFIG_MANAGER.get_catalogue_settings()
        dl_policy = cat_settings.get("download_policy", "authenticated")
        u_role = session.get("role", "Patron")
        can_download = True
        if dl_policy == "admin_only" and u_role != "Administrator":
            can_download = False
        elif dl_policy == "faculty_admin" and u_role not in ("Administrator", "Faculty", "Staff"):
            can_download = False

        return {
            "book_id": book_id,
            "library_id": target_lib["library_id"],
            "title": title or "Untitled",
            "authors": authors,
            "publisher": publisher,
            "year": year,
            "page_count": page_count,
            "file_size": os.path.getsize(candidate_pdf),
            "pdf_path": candidate_pdf,
            "can_download": can_download,
            "formats": [str(r[0]).lower() for r in fmt_rows]
        }, 200, None

    def handle_reader_info(self, query: dict):
        session, code, err = self._get_active_reader_session()
        if not session:
            self.send_json(code, {"error": err})
            return

        info, status, err_msg = self._resolve_authorized_book_pdf(session, query)
        if not info:
            self.send_json(status, {"error": err_msg})
            return

        inst = CONFIG_MANAGER.get_institution_settings()
        payload = {
            "book_id": info["book_id"],
            "library_id": info["library_id"],
            "title": info["title"],
            "authors": info["authors"],
            "publisher": info["publisher"],
            "year": info["year"],
            "page_count": info["page_count"],
            "file_size": info["file_size"],
            "can_download": info["can_download"],
            "formats": info["formats"],
            "branding": {
                "institution_name": inst.get("institution_name") or "Institutional Digital Library",
                "short_name": inst.get("short_name") or "IDL",
                "logo_url": inst.get("logo_path") or "/static/images/institution-mark.svg",
                "primary_color": inst.get("primary_color") or "#183c34"
            }
        }
        self.send_json(200, payload, extra_headers={"Cache-Control": "private, no-store, no-cache, must-revalidate, max-age=0"})

    def handle_reader_page(self, query: dict):
        session, code, err = self._get_active_reader_session()
        if not session:
            self.send_json(code, {"error": err})
            return

        info, status, err_msg = self._resolve_authorized_book_pdf(session, query)
        if not info:
            self.send_json(status, {"error": err_msg})
            return

        raw_page = (query.get("page") or ["1"])[0].strip()
        raw_dpi = (query.get("dpi") or ["150"])[0].strip()
        if not raw_page.isdigit():
            self.send_json(400, {"error": "Invalid page number."})
            return
        page_num = int(raw_page)
        if page_num < 1 or page_num > info["page_count"]:
            self.send_json(404, {"error": f"Page {page_num} is out of bounds (1..{info['page_count']})."})
            return

        dpi = int(raw_dpi) if raw_dpi.isdigit() else 150
        dpi = max(72, min(250, dpi))

        png_bytes = render_pdf_page_to_png(info["pdf_path"], page_num, dpi=dpi)
        if not png_bytes:
            self.send_json(422, {"error": f"Unable to render page {page_num} of the PDF document."})
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png_bytes)))
        self.send_header("Cache-Control", "private, no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(png_bytes)

    def handle_reader_search(self, query: dict):
        session, code, err = self._get_active_reader_session()
        if not session:
            self.send_json(code, {"error": err})
            return

        info, status, err_msg = self._resolve_authorized_book_pdf(session, query)
        if not info:
            self.send_json(status, {"error": err_msg})
            return

        q_str = (query.get("q") or [""])[0].strip()
        if not q_str:
            self.send_json(200, {"query": "", "total_matches": 0, "results": []})
            return

        matches = search_pdf_document_text(info["pdf_path"], q_str)
        total_hits = sum(m.get("matches_on_page", 1) for m in matches)
        self.send_json(200, {
            "query": q_str,
            "total_matches": total_hits,
            "results": matches
        }, extra_headers={"Cache-Control": "private, no-store, no-cache, must-revalidate, max-age=0"})

    def handle_reader_stream(self, query: dict, head_only: bool = False):
        session, code, err = self._get_active_reader_session()
        if not session:
            self.send_json(code, {"error": err})
            return

        info, status, err_msg = self._resolve_authorized_book_pdf(session, query)
        if not info:
            self.send_json(status, {"error": err_msg})
            return

        # Enforce institutional download policy on raw PDF stream / download
        if not info["can_download"]:
            self.send_json(403, {"error": "Direct PDF file downloads are restricted by institutional library policy. Please use the online page reader."})
            return

        pdf_path = info["pdf_path"]
        total_size = info["file_size"]
        is_download = (query.get("download") or ["0"])[0] == "1"
        safe_filename = re.sub(r'[^A-Za-z0-9._ -]', '_', info["title"]).strip() or f"book_{info['book_id']}"
        disposition = f'attachment; filename="{safe_filename}.pdf"' if is_download else f'inline; filename="{safe_filename}.pdf"'

        range_header = self.headers.get("Range", "").strip()
        if range_header.startswith("bytes="):
            try:
                range_spec = range_header[len("bytes="):].split(",")[0].strip()
                start_str, end_str = range_spec.split("-", 1)
                if start_str == "":
                    suffix_len = int(end_str)
                    start = max(0, total_size - suffix_len)
                    end = total_size - 1
                else:
                    start = int(start_str)
                    end = int(end_str) if end_str else total_size - 1
                if start < 0 or start >= total_size or end < start:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total_size}")
                    apply_no_cache_headers(self)
                    self.end_headers()
                    return
                end = min(end, total_size - 1)
                chunk_len = end - start + 1

                self.send_response(206)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
                self.send_header("Content-Length", str(chunk_len))
                self.send_header("Content-Disposition", disposition)
                self.send_header("Cache-Control", "private, no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if not head_only:
                    with open(pdf_path, "rb") as f:
                        f.seek(start)
                        self.wfile.write(f.read(chunk_len))
                return
            except ValueError:
                pass

        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(total_size))
        self.send_header("Content-Disposition", disposition)
        self.send_header("Cache-Control", "private, no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            with open(pdf_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

    def proxy_to_calibre(self, head_only=False):
        token = self.get_session_token()
        session = get_session(token)

        if not session:
            accept = self.headers.get("Accept", "")
            if "text/html" in accept or "application/xhtml+xml" in accept:
                self._redirect_to_login()
                return
            else:
                self.send_json(401, {"error": "Authentication required. Please sign in at the institutional portal."})
                return

        # Verify user is still active
        prof = CONFIG_MANAGER.get_user_profile(session["username"])
        if not prof.get("is_active", True):
            destroy_session(token)
            self.send_json(403, {"error": "Account deactivated."})
            return

        parsed = urllib.parse.urlparse(self.path)
        query_dict = urllib.parse.parse_qs(parsed.query)

        # Enforce Backend Per-Library Access Control
        req_lib = self._extract_requested_calibre_library(parsed.path, query_dict)
        if req_lib and not CONFIG_MANAGER.is_user_allowed_library(session["username"], session["role"], req_lib):
            self.send_json(403, {"error": "Access restricted: Your institutional role or account scope does not permit access to this library collection."})
            return

        # Enforce Read-Only & Non-Admin Protection on ALL Calibre modification, conversion, deletion, note & FTS routes
        restricted_calibre_segments = (
            "/cdb/",
            "/conversion/",
            "/ajax/set-fields",
            "/ajax/delete-books",
            "/set-note/",
            "/data-files/upload",
            "/data-files/remove",
            "/fts/disable",
            "/fts/reindex",
            "/fts/indexing",
        )
        if any(seg in parsed.path for seg in restricted_calibre_segments):
            if session.get("readonly", True) or session.get("role") != "Administrator":
                self.send_json(403, {"error": "Read-Only Enforcement: Modifying, converting, or deleting repository books is prohibited for this account."})
                return

        # Enforce Catalogue Download Policy on direct book file downloads (/calibre/get/<what>/...)
        cat_settings = CONFIG_MANAGER.get_catalogue_settings()
        if parsed.path.startswith("/calibre/get/"):
            parts = [p for p in parsed.path.split("/") if p]
            what = parts[2].lower() if len(parts) >= 3 else ""
            is_inline = query_dict.get("content_disposition", [""])[0] == "inline"
            if what not in ("cover", "thumb") and not is_inline:
                dl_policy = cat_settings.get("download_policy", "authenticated")
                u_role = session.get("role", "Patron")
                if dl_policy == "admin_only" and u_role != "Administrator":
                    self.send_json(403, {"error": "Direct file downloads are restricted to Administrators. Please use the in-browser reader."})
                    return
                if dl_policy == "faculty_admin" and u_role not in ("Administrator", "Faculty", "Staff"):
                    self.send_json(403, {"error": "Direct file downloads are restricted to Faculty, Staff, and Administrators."})
                    return

        upstream_path = self.path
        if not upstream_path.startswith("/calibre"):
            upstream_path = f"/calibre{upstream_path}"
        target_url = f"{BACKEND_ORIGIN}{upstream_path}"

        req = urllib.request.Request(target_url, method=self.command)
        skip_headers = {"host", "authorization", "cookie", "connection", "keep-alive", "cache-control", "pragma", "expires", "accept-encoding"}
        for k, v in self.headers.items():
            if k.lower() not in skip_headers:
                req.add_header(k, v)

        req.add_header("Authorization", f"Basic {session['basic_auth']}")

        if self.command in ("POST", "PUT", "PATCH"):
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                req.data = self.rfile.read(length)

        try:
            with urllib.request.urlopen(req, timeout=15) as upstream_resp:
                content_type = upstream_resp.headers.get("Content-Type", "")
                content_encoding = upstream_resp.headers.get("Content-Encoding", "").lower()
                status_code = upstream_resp.status
                content = upstream_resp.read()

                if "gzip" in content_encoding:
                    try:
                        content = gzip.decompress(content)
                    except Exception:
                        pass
                elif "deflate" in content_encoding:
                    try:
                        content = zlib.decompress(content)
                    except Exception:
                        pass

                # Enrich /calibre/institutional/api JSON response with live branding, catalogue settings & filtered libraries
                if parsed.path.rstrip("/") == "/calibre/institutional/api" and "application/json" in content_type.lower() and not head_only:
                    try:
                        payload_obj = json.loads(content.decode("utf-8"))
                        inst = CONFIG_MANAGER.get_institution_settings()
                        payload_obj["branding"] = {
                            "institution_name": inst.get("institution_name") or "Aethelgard Institute of Technology",
                            "short_name": inst.get("short_name") or "AIT",
                            "library_title": inst.get("library_title") or "The Institutional Library",
                            "motto": inst.get("motto") or "Knowledge Preserved, Universally Accessible",
                            "logo_url": inst.get("logo_path") or "/static/images/institution-mark.svg",
                            "primary_color": inst.get("primary_color") or "#183c34",
                            "portal_url": f"http://{HOST}:{PORT}"
                        }
                        payload_obj["catalogue_settings"] = cat_settings
                        u_role = session.get("role", "Patron")
                        payload_obj["user_role"] = u_role
                        payload_obj["user_display_name"] = session.get("displayName") or session.get("username") or ""

                        for b_item in payload_obj.get("books") or []:
                            if u_role == "Administrator":
                                b_item["allow_native"] = True
                            else:
                                b_item["allow_native"] = False
                                b_item.pop("native_url", None)

                        # Filter libraries map by user authorization & map friendly display names
                        cfg_libs = CONFIG_MANAGER.get_libraries()
                        friendly_map = {}
                        for cl in cfg_libs:
                            bname = os.path.basename(cl.get("path", "")).replace(" ", "_")
                            friendly_map[cl["library_id"].lower()] = cl["display_name"]
                            friendly_map[bname.lower()] = cl["display_name"]

                        raw_libs = payload_obj.get("libraries") or {}
                        filtered_libs = {}
                        for lid, lname in raw_libs.items():
                            if CONFIG_MANAGER.is_user_allowed_library(session["username"], session["role"], lid):
                                filtered_libs[lid] = friendly_map.get(lid.lower(), lname)
                        payload_obj["libraries"] = filtered_libs
                        content = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")
                    except Exception as ex:
                        logger.warning("Failed to enrich institutional API payload: %s", ex)

                if "text/html" in content_type.lower() and not head_only and '/institutional' not in upstream_path:
                    if cat_settings.get("inject_bar", True):
                        try:
                            html_str = content.decode("utf-8", errors="replace")
                            injected_ui = build_injected_institutional_ui(session)
                            rpos = html_str.rfind("</body>")
                            if rpos != -1:
                                html_str = html_str[:rpos] + injected_ui + "\n" + html_str[rpos:]
                            else:
                                rpos = html_str.rfind("</html>")
                                if rpos != -1:
                                    html_str = html_str[:rpos] + injected_ui + "\n" + html_str[rpos:]
                                else:
                                    html_str += injected_ui
                            content = html_str.encode("utf-8")
                        except Exception as e:
                            print(f"[Gateway Error] HTML injection error: {e}")

                self.send_response(status_code)
                for k, v in upstream_resp.headers.items():
                    if k.lower() not in ("content-length", "content-encoding", "transfer-encoding", "connection", "set-cookie", "www-authenticate"):
                        self.send_header(k, v)

                self.send_header("Content-Length", str(len(content)))
                apply_no_cache_headers(self)
                self.end_headers()

                if not head_only:
                    self.wfile.write(content)

        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                accept = self.headers.get("Accept", "")
                is_ajax = self.headers.get("X-Requested-With", "").lower() == "xmlhttprequest" or any(
                    s in parsed.path for s in ("/ajax", "/interface-data", "/book-get-", "/book-set-")
                )
                if "text/html" in accept and not is_ajax:
                    self.send_response(302)
                    self.send_header("Location", "/?login_required=1")
                    apply_no_cache_headers(self)
                    self.end_headers()
                else:
                    self.send_json(e.code, {"error": "Upstream authentication or permission error", "status": e.code})
            else:
                self.send_safe_error(e.code, "Upstream Service Error")
        except Exception as e:
            print(f"[Gateway Error] Upstream proxy error: {e}")
            self.send_safe_error(502, "Bad Gateway")


class InstitutionalGatewayServer(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def run_gateway():
    sync_branding_json_file()
    if CONFIG_MANAGER.is_setup_completed() and not BACKEND_SUPERVISOR.start_backend():
        raise RuntimeError('Calibre backend did not start; gateway was not exposed.')
    cfg_bind = CONFIG_MANAGER.get_config_value("network_bind_mode")
    bind_host = "0.0.0.0" if cfg_bind in ("0.0.0.0", "custom_lan", "all") else CONFIG.get("gateway_host", "127.0.0.1")
    server_address = (bind_host, PORT)
    httpd = InstitutionalGatewayServer(server_address, InstitutionalGatewayHandler)
    print(f"============================================================")
    print(f" Institutional Authentication Gateway & Administration Core ")
    print(f" Port: {PORT} (PID: {os.getpid()})                           ")
    print(f" Backend URL: {BACKEND_URL}                                 ")
    print(f" Setup Status: {'Completed' if CONFIG_MANAGER.is_setup_completed() else 'Incomplete (Redirecting to /setup)'} ")
    print(f"============================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Gateway] Shutting down server...")
        httpd.server_close()


if __name__ == "__main__":
    run_gateway()
