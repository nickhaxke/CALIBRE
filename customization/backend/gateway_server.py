# -*- coding: utf-8 -*-
"""
Institutional Authentication Gateway & Reverse Proxy Server (Phase 4)
Integrates with upstream Calibre Content Server while enforcing:
- First-time setup wizard routing & locking
- Institutional administration portal & REST APIs
- Versioned SQLite configuration management
- Official Calibre CLI user administration
- Individual patron authentication and session invalidation
- Dynamic institutional branding and navigation bar injection
- Anti-caching and security hardening defenses
"""
import base64
import gzip
import html
import http.client
import json
import ipaddress
import logging
import mimetypes
import os
import secrets
import socket
import sqlite3
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
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir).lower() == "bin":
            return os.path.dirname(exe_dir)
        return exe_dir
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.abspath(os.path.join(here, "..", ".."))
    if os.path.isdir(os.path.join(candidate, "customization")):
        return candidate
    return r"C:\dev\calibre-institutional"

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
PORT = CONFIG.get("gateway_port", 8085)
BACKEND_URL = CONFIG.get("calibre_backend_url", "http://127.0.0.1:8088/calibre")
_backend_address = urllib.parse.urlparse(BACKEND_URL)
if _backend_address.scheme != 'http' or not ipaddress.ip_address(_backend_address.hostname).is_loopback:
    raise ValueError('The Calibre backend must use loopback HTTP.')
BACKEND_ORIGIN = f'{_backend_address.scheme}://{_backend_address.netloc}'
COOKIE_NAME = CONFIG.get("session_cookie_name", "inst_session_id")
SESSION_TIMEOUT = CONFIG.get("session_timeout_seconds", 28800)

# Global Configuration & User Managers
CONFIG_MANAGER = ConfigManager()
USER_MANAGER = CalibreUserManager(config_manager=CONFIG_MANAGER)
BACKEND_SUPERVISOR = BackendSupervisor(config_manager=CONFIG_MANAGER, port=_backend_address.port or 8088, host=_backend_address.hostname)

# In-Memory Thread-Safe Session Store
# token -> {username, role, displayName, basic_auth, expires_at}
SESSIONS = {}
SESSION_LOCK = threading.Lock()

# Fallback User Role Directory for legacy test fixtures
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
FAILED_LOGIN_ATTEMPTS = {}  # ip -> [timestamp1, timestamp2, ...]
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

def create_session(username, password):
    token = secrets.token_urlsafe(32)
    b64_auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    
    # Query role and displayName from persistent configuration store
    profile = CONFIG_MANAGER.get_user_profile(username)
    if profile:
        role = profile.get("role", "Patron")
        display_name = profile.get("display_name", username)
    else:
        role_info = USER_ROLES.get(username, {"role": "Patron", "displayName": username})
        role = role_info.get("role", "Patron")
        display_name = role_info.get("displayName", username)
    
    with SESSION_LOCK:
        SESSIONS[token] = {
            "username": username,
            "role": role,
            "displayName": display_name,
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

    safe_user = html.escape(raw_user)
    safe_role = html.escape(raw_role)
    safe_display = html.escape(raw_display)

    inst = CONFIG_MANAGER.get_institution_settings()
    inst_name = html.escape(inst.get("name") or inst.get("institution_name") or "Aethelgard Institute of Technology")
    inst_short = html.escape(inst.get("short_name") or "AIT")

    admin_link = ""
    if session.get("role") == "Administrator":
        admin_link = '<a href="/admin" class="inst-nav-link" id="inst-nav-admin-btn" style="border-color: #c99738; color: #fbbf24;">Admin Console</a>'

    return f'''
<!-- INSTITUTIONAL CALIBRE INTEGRATION BAR -->
<div id="inst-calibre-nav" role="banner" aria-label="Institutional Navigation">
  <div class="inst-nav-container">
    <div class="inst-nav-left">
      <a href="/" class="inst-nav-brand" title="Return to Institutional Portal">
        <span class="inst-nav-seal">{inst_short}</span>
        <span class="inst-nav-title">{inst_name}</span>
        <span class="inst-nav-sub">| Institutional Library</span>
      </a>
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

<style id="inst-calibre-styles">
  #inst-calibre-nav {{
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    height: 44px !important;
    background: #0f172a !important;
    border-bottom: 2px solid #c5a059 !important;
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
    background: #c5a059 !important;
    color: #0f172a !important;
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
</style>

<script id="inst-calibre-bridge">
(function() {{
  "use strict";

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
        pass  # Suppress standard console clutter

    def get_client_ip(self):
        forwarded = self.headers.get("X-Forwarded-For")
        if self.client_address[0] in CONFIG.get('trusted_proxies', []) and forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def is_valid_csrf_origin(self):
        origin = self.headers.get("Origin")
        referer = self.headers.get("Referer")
        host = self.headers.get("Host", "")
        trusted = CONFIG.get('allowed_origins', []) or [f'http://{host}', f'https://{host}']

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
        try:
            address = ipaddress.ip_address(self.client_address[0])
            local = address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
            return local and self.client_address[0] not in CONFIG.get('trusted_proxies', [])
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

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/static/"):
            self.serve_static(path, head_only=True)
            return
        if path.startswith("/calibre"):
            token = self.get_session_token()
            session = get_session(token)
            if not session:
                self.send_response(302)
                self.send_header("Location", "/?login_required=1")
                apply_no_cache_headers(self)
                self.end_headers()
                return
            self.proxy_to_calibre(head_only=True)
            return
        self.send_error(404, "Endpoint Not Found")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 0. First-Time Setup Gatekeeper:
        # If setup is incomplete, redirect unauthenticated users to /setup
        if not CONFIG_MANAGER.is_setup_completed():
            allowed_prefixes = ("/setup", "/static/", "/api/setup/")
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
        if path == "/setup" or path == "/setup/":
            self.serve_setup_page()
            return

        # 3. Setup Status API
        if path == "/api/setup/status":
            self.handle_setup_status()
            return

        # 4. Institutional Administration Portal Page
        if path == "/admin" or path == "/admin/":
            self.serve_admin_page()
            return

        # 5. Admin REST APIs (Protected: Administrator only)
        if path == "/api/admin/dashboard":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.handle_admin_dashboard()
            return

        if path == "/api/admin/settings":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.send_json(200, CONFIG_MANAGER.get_institution_settings())
            return

        if path == "/api/admin/libraries":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.send_json(200, CONFIG_MANAGER.get_libraries())
            return

        if path == "/api/admin/users":
            session, code, err = self.require_admin()
            if not session:
                self.send_json(code, {"error": err})
                return
            self.send_json(200, USER_MANAGER.list_users())
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
            self.send_json(200, CONFIG_MANAGER.get_audit_log(limit=100))
            return

        # 6. Static Assets
        if path.startswith("/static/"):
            self.serve_static(path)
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
                        "displayName": session["displayName"]
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
            self.serve_catalog()
            return

        # 10. Reverse Proxy to Calibre (/calibre/*)
        if path.startswith("/calibre") or path.startswith("/calibre/"):
            self.proxy_to_calibre()
            return

        self.send_error(404, "Endpoint Not Found")

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
            "/api/admin/libraries",
            "/api/admin/libraries/default",
            "/api/admin/libraries/toggle",
            "/api/admin/libraries/remove",
            "/api/admin/users/create",
            "/api/admin/users/change-password",
            "/api/admin/users/readonly",
            "/api/admin/users/profile",
            "/api/admin/users/remove",
            "/api/admin/system/backup",
            "/api/admin/system/reload"
            , "/api/admin/system/shutdown"
        )

        if path in admin_post_endpoints:
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
        if path.startswith("/calibre"):
            self.proxy_to_calibre()
            return

        self.send_error(404, "Endpoint Not Found")

    # ==============================================================================
    # Setup Wizard Handlers
    # ==============================================================================
    def serve_setup_page(self):
        # Security Hardening: Setup access is restricted to localhost when incomplete
        if not CONFIG_MANAGER.is_setup_completed() and not self.is_local_request():
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>403 Forbidden</h1><p>First-time setup can only be accessed from the local server machine (127.0.0.1).</p>")
            return

        # If setup is already finished, redirect to /admin or /
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
        calibre_bin = r"C:/Program Files/Calibre2/calibre-server.exe"
        calibre_installed = os.path.isfile(calibre_bin)
        
        calibre_ver = "7.x"
        if calibre_installed:
            try:
                import subprocess
                res = subprocess.run([calibre_bin, "--version"], capture_output=True, text=True, timeout=5)
                calibre_ver = res.stdout.strip()
            except Exception:
                calibre_ver = "7.x"

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
        
        # Path validation: prevent arbitrary system folder probing
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

        # Query read-only book count
        books_count = 0
        try:
            conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True, timeout=5.0)
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM books")
            row = cur.fetchone()
            books_count = row[0] if row else 0
            conn.close()
        except Exception as e:
            self.send_json(200, {"valid": False, "error": f"Failed to inspect metadata.db: {e}"})
            return

        self.send_json(200, {"valid": True, "path": norm_path, "books_count": books_count})

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
            # 1. Provision Administrator in Calibre CLI userdb
            # Check if user already exists in userdb (e.g. librarian1)
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

            # 2. Update Institution Settings
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

            # 3. Register Primary Library
            CONFIG_MANAGER.add_library(
                display_name=lib_name or "Main Academic Collection",
                path=os.path.abspath(lib_path),
                is_default=True,
                is_active=True,
                actor="SetupBootstrap"
            )

            # 4. Mark Setup Completed
            CONFIG_MANAGER.set_setup_completed(True, actor="SetupBootstrap")
            try:
                BACKEND_SUPERVISOR.sync_libraries()
            except Exception as sync_err:
                logger.warning("Backend library sync notice: %s", sync_err)

            print(f"[Gateway Setup] Institution '{inst_name}' bootstrapped successfully by {admin_user}")
            self.send_json(200, {"success": True, "redirect": "/admin"})
        except Exception as e:
            print(f"[Gateway Setup Error] {e}")
            self.send_json(500, {"success": False, "error": f"Failed to complete setup: {e}"})

    # ==============================================================================
    # Administration Portal Handlers
    # ==============================================================================
    def serve_admin_page(self):
        token = self.get_session_token()
        session = get_session(token)
        if not session:
            self.send_response(302)
            self.send_header("Location", "/?login_required=1")
            apply_no_cache_headers(self)
            self.end_headers()
            return

        if session.get("role") != "Administrator":
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>403 Forbidden</h1><p>Institutional Administrator privileges required to access administration portal.</p>")
            return

        admin_file = os.path.join(TEMPLATES_DIR, "admin.html")
        if not os.path.exists(admin_file):
            self.send_error(500, "Admin template missing")
            return
        with open(admin_file, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        apply_no_cache_headers(self)
        self.end_headers()
        self.wfile.write(content)

    def handle_admin_dashboard(self):
        inst = CONFIG_MANAGER.get_institution_settings()
        libs = CONFIG_MANAGER.get_libraries()
        users = USER_MANAGER.list_users()
        recent_audit = CONFIG_MANAGER.get_audit_log(limit=6)

        # Check Calibre Backend status
        backend_online = BACKEND_SUPERVISOR.is_backend_responsive()

        data = {
            "institution": inst,
            "libraries": libs,
            "users_count": len(users),
            "recent_audit": recent_audit,
            "system": {
                "gateway_port": PORT,
                "storage_mode": "SQLite (Phase 4)",
                "calibre_backend_online": backend_online
            }
        }
        self.send_json(200, data)

    def handle_admin_system(self):
        backend_online = BACKEND_SUPERVISOR.is_backend_responsive()

        # Gather LAN IPs
        lan_ips = []
        try:
            hostname = socket.gethostname()
            _, _, ips = socket.gethostbyname_ex(hostname)
            lan_ips = [ip for ip in ips if not ip.startswith("127.")]
        except Exception:
            lan_ips = ["127.0.0.1"]

        data = {
            "gateway_port": PORT,
            "calibre_port": _backend_address.port or 8088,
            "calibre_backend_online": backend_online,
            "lan_ips": lan_ips,
            "db_path": CONFIG_MANAGER.db_path,
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

        # 1. Update Institution Settings
        if path == "/api/admin/settings":
            try:
                CONFIG_MANAGER.update_institution_settings(
                    name=req.get("name", "").strip(),
                    short_name=req.get("short_name", "").strip(),
                    library_name=req.get("library_name", "").strip(),
                    motto=req.get("motto", "").strip(),
                    contact_email=req.get("contact_email", "").strip(),
                    contact_phone=req.get("contact_phone", "").strip(),
                    logo_url=req.get("logo_url", "").strip(),
                    actor=actor
                )
                self.send_json(200, {"success": True})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 2. Add Library
        if path == "/api/admin/libraries":
            label = req.get("display_name", "").strip()
            lib_path = req.get("library_path", "").strip()
            is_def = bool(req.get("is_default", False))
            
            if not lib_path or not os.path.isfile(os.path.join(lib_path, "metadata.db")):
                self.send_json(400, {"success": False, "error": "metadata.db not found in specified directory."})
                return

            try:
                CONFIG_MANAGER.add_library(
                    display_name=label or os.path.basename(lib_path),
                    path=os.path.abspath(lib_path),
                    is_default=is_def,
                    is_active=True,
                    actor=actor
                )
                try:
                    BACKEND_SUPERVISOR.sync_libraries()
                except Exception as ex:
                    logger.warning("Backend synchronization notice: %s", ex)
                self.send_json(200, {"success": True})
            except Exception as e:
                self.send_json(400, {"success": False, "error": str(e)})
            return

        # 3. Set Default Library
        if path == "/api/admin/libraries/default":
            lib_id = req.get("library_id") or req.get("id")
            if not lib_id:
                self.send_json(400, {"success": False, "error": "library_id required"})
                return
            CONFIG_MANAGER.update_library(lib_id, is_default=True, actor=actor)
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

            try:
                res = USER_MANAGER.add_user(
                    username=u,
                    password=p,
                    full_name=fn,
                    role=r,
                    department=dept,
                    readonly=ro,
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

        if path == '/api/admin/users/profile':
            USER_MANAGER.update_profile(req.get('username', ''), req.get('full_name', ''), req.get('role', 'Patron'), req.get('department', ''), actor=actor)
            with SESSION_LOCK:
                for token in list(SESSIONS):
                    if SESSIONS[token]['username'] == req.get('username'):
                        del SESSIONS[token]
            self.send_json(200, {'success': True})
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

        # 10. Backup Database
        if path == "/api/admin/system/backup":
            try:
                bp = CONFIG_MANAGER.create_backup()
                self.send_json(200, {"success": True, "backup_path": bp})
            except Exception as e:
                self.send_json(500, {"success": False, "error": str(e)})
            return

        # 11. Reload Cache
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
        name_val = inst.get("name") or inst.get("institution_name") or "Aethelgard Institute of Technology"
        short_val = inst.get("short_name") or "AIT"
        lib_val = inst.get("library_name") or inst.get("library_title") or "Institutional Digital Library & Research Repository"
        motto_val = inst.get("motto") or "Academic Volumes, Digital Collections & Faculty Research"
        rendered = template.replace("{{INSTITUTION_NAME}}", html.escape(name_val))
        rendered = rendered.replace("{{INSTITUTION_SHORT_NAME}}", html.escape(short_val))
        rendered = rendered.replace("{{LIBRARY_DISPLAY_NAME}}", html.escape(lib_val))
        rendered = rendered.replace("{{INSTITUTION_MOTTO}}", html.escape(motto_val))
        branding_path = os.environ.get('CALIBRE_INSTITUTIONAL_BRANDING')
        if branding_path:
            with open(branding_path, encoding='utf-8') as stream:
                brand = json.load(stream)
            for key, value in (('INSTITUTION_NAME', brand.get('institution_name', name_val)), ('INSTITUTION_SHORT_NAME', brand.get('short_name', short_val))):
                # Render from the original template so settings stay consistent with the source view.
                template = template.replace('{{' + key + '}}', html.escape(value))
            rendered = template.replace('{{LIBRARY_DISPLAY_NAME}}', html.escape(brand.get('library_title', lib_val))).replace('{{INSTITUTION_MOTTO}}', html.escape(brand.get('motto', motto_val)))
        rendered = rendered.replace('{{LOGO_URL}}', html.escape((brand.get('logo_url') if branding_path else inst.get('logo_path')) or '', quote=True))
        rendered = rendered.replace("{{CONTACT_EMAIL}}", html.escape(inst.get("contact_email", "library@nipa.ac.zm")))
        rendered = rendered.replace("{{CONTACT_PHONE}}", html.escape(inst.get("contact_phone", "+260 211 256177")))
        
        content = rendered.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        apply_no_cache_headers(self)
        self.end_headers()
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

    def serve_catalog(self):
        token = self.get_session_token()
        session = get_session(token)
        if not session:
            self.send_json(401, {"error": "Authentication required. Please sign in with your institutional credentials to browse repository volumes."})
            return

        url = f"{BACKEND_URL}/ajax/books"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {session['basic_auth']}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            books = []
            for bid, binfo in data.items():
                books.append({
                    "id": binfo.get("application_id", bid),
                    "title": binfo.get("title", "Untitled"),
                    "author": ", ".join(binfo.get("authors", ["Unknown"])),
                    "description": binfo.get("comments") or "Authoritative institutional repository publication.",
                    "formats": binfo.get("formats", ["epub"])
                })
            self.send_json(200, books)
        except urllib.error.HTTPError as he:
            if he.code in (401, 403):
                self.send_json(403, {"error": "Access restricted: Your institutional account does not have permission for this repository collection."})
            else:
                self.send_json(503, {"error": "Institutional repository service is temporarily unavailable."})
        except Exception as e:
            print(f"[Gateway Error] Upstream catalog error: {e}")
            self.send_json(503, {"error": "Institutional repository service is temporarily unavailable."})

    def proxy_to_calibre(self, head_only=False):
        token = self.get_session_token()
        session = get_session(token)

        if not session:
            accept = self.headers.get("Accept", "")
            if "text/html" in accept or "application/xhtml+xml" in accept:
                self.send_response(302)
                self.send_header("Location", "/?login_required=1")
                apply_no_cache_headers(self)
                self.end_headers()
                return
            else:
                self.send_json(401, {"error": "Authentication required. Please sign in at the institutional portal."})
                return

        upstream_path = self.path
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

                if "text/html" in content_type.lower() and not head_only and '/institutional' not in upstream_path:
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
                self.send_response(302)
                self.send_header("Location", "/?login_required=1")
                apply_no_cache_headers(self)
                self.end_headers()
            else:
                self.send_error(e.code, "Upstream Service Error")
        except Exception as e:
            print(f"[Gateway Error] Upstream proxy error: {e}")
            self.send_error(502, "Bad Gateway")

class InstitutionalGatewayServer(ThreadingHTTPServer):
    # A page can request many covers at once; the default backlog of five can
    # reject legitimate browser connections before a handler thread is created.
    request_queue_size = 128
    daemon_threads = True


def run_gateway():
    if CONFIG_MANAGER.is_setup_completed() and not BACKEND_SUPERVISOR.start_backend():
        raise RuntimeError('Calibre backend did not start; gateway was not exposed.')
    server_address = (HOST, PORT)
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
        print("\n[Gateway] Shutting down cleanly.")
        httpd.server_close()
    finally:
        httpd.server_close()
        BACKEND_SUPERVISOR.stop_backend()

if __name__ == "__main__":
    run_gateway()
