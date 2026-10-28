# Phase 1 Implementation, LAN DNS, HTTPS & Packaging Requirements
**Project:** Calibre Institutional Customization  
**Phase:** Phase 1 — Institutional Calibre MVP  
**Status:** Implemented & Verified Locally  

---

## 1. Prototype Architecture & Verification

The Phase 1 prototype demonstrates a complete, secure institutional digital library that keeps the Calibre Desktop application intact for administrators while providing individual student/faculty authentication:

```
[ Campus LAN / Wi-Fi Device: 192.168.0.x ]
                  │
                  ▼
[ Institutional Gateway: http://192.168.0.107:8085/ ]
  ├── Branded HTML5/CSS3 Landing Page & Search
  ├── Individual Patron Authentication (student1, faculty1, librarian1)
  ├── Cryptographic Session Manager (HttpOnly Cookies)
  └── Gatekeeper Reverse Proxy Router (/calibre/*)
                  │
                  ▼ (Loopback 127.0.0.1:8088 Only)
[ Calibre Content Server Backend ]
  ├── Enforces Basic Authentication with server-users.sqlite
  ├── In-Browser eBook Reader & Annotations
  └── Isolated Test Library (metadata.db)
```

### Verified Prototype Journey
1. **Landing Page:** Patrons connect to `http://192.168.0.107:8085/`.
2. **Access Control:** Unauthenticated users cannot access `/calibre/` or book files; direct requests to port `8088` from LAN are dropped because the backend is bound to `127.0.0.1`.
3. **Authentication:** User logs in with individual credentials (e.g. `student1` / `StudentPass123!`).
4. **Session Bridge:** The gateway sets an `inst_session_id` cookie and proxies all `/calibre/*` requests upstream with the user's individual `Authorization: Basic` token.
5. **Browse & Read:** The patron browses catalog volumes, views metadata, and reads EPUB books directly in the browser via `/calibre/get/epub/1/library` and the web reader.
6. **Sign Out:** The patron signs out, invalidating the session token immediately.

---

## 2. Requirements for Subsequent Phases

### 2.1 Campus LAN DNS Resolution
To move from an IP-based URL (`http://192.168.0.107:8085/`) to a branded institutional domain (`http://library.campus.local/` or `https://library.ait.edu/`):
1. **Local DNS Server Record:** Add an `A` record on the institution's primary DNS/Active Directory server:
   ```
   library.campus.local.   IN  A   192.168.0.107
   ```
2. **mDNS (Zero-Configuration):** For smaller departments without a centralized DNS server, advertise the service via Bonjour/mDNS (`library.local`), which Calibre already supports via `src/calibre/srv/bonjour.py`.

### 2.2 HTTPS / TLS Termination
To secure campus Wi-Fi traffic against packet sniffing and comply with modern browser security policies (PWA service workers, clipboard permissions in e-reader):
1. **Reverse Proxy TLS Termination:** Terminate SSL/TLS on Apache (port 443) or Nginx on the server.
2. **Institutional CA Certificate:** Deploy a certificate issued by the university's internal Certificate Authority or a public Let's Encrypt certificate for the institutional domain.
3. **Gateway Forwarding:** Forward incoming HTTPS requests to the gateway on port 8085 with standard `X-Forwarded-Proto: https` headers.

### 2.3 Windows Packaging & Daemonization
To run the Institutional Library as an unattended Windows system service without requiring an open command prompt:
1. **Windows Service Wrapping:** Use **WinSW** (Windows Service Wrapper) or **NSSM** (Non-Sucking Service Manager) to register:
   - Service 1: `CalibreTestContentServer` (`calibre-server.exe` on port 8088)
   - Service 2: `InstitutionalGatewayService` (`python gateway_server.py` on port 8085)
2. **Institutional Desktop Distribution (Phase 5):**
   - Use **Inno Setup** to package a single Windows installer.
   - The installer creates institutional desktop shortcuts ("AIT Library Manager"), pre-configures server parameters in `%APPDATA%\calibre\server-config.txt`, and registers the background services.
