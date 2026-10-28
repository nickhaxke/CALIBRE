# Security Architecture, Threat Modeling & Required Controls
**Project:** Calibre Institutional Customization  
**Phase:** Phase 0 — Security Assessment  
**Audit Target:** Local & LAN Institutional Digital Library Deployment  
**Security Standard:** OWASP Top 10 / Enterprise LAN Hardening  

---

## 1. Threat Modeling for Institutional LAN / Wi-Fi

Deploying a digital library on a shared campus Wi-Fi or LAN environment introduces specific security vulnerabilities that must be mitigated prior to production launch:

```
                  UNTRUSTED CAMPUS LAN / WI-FI
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
   [Attacker on Wi-Fi]                   [Legitimate Student]
            │                                     │
   Packet Sniffing (HTTP)                         │
   Direct Port 8080 Bypass                        │
            │                                     ▼
            │                        ┌────────────────────────┐
            │                        │  Institutional Gateway │
            │                        │  (Port 80/443 + TLS)   │
            │                        └────────────┬───────────┘
            │                                     │ Validated Proxy
            ▼                                     ▼
   ┌──────────────────────────────────────────────────────────┐
   │ Loopback-Only Host Boundary (127.0.0.1)                  │
   │   Calibre Content Server (Port 8080)                    │
   │   Calibre Library (metadata.db - Read Only)             │
   └──────────────────────────────────────────────────────────┘
```

### 1.1 Identified Vulnerabilities & Risk Profiles

| Threat Identifier | Vulnerability Description | Severity | Impact on Institutional Environment |
| :--- | :--- | :--- | :--- |
| **THREAT-01: Cleartext Transmission** | Content Server currently operates over unencrypted HTTP on port 8080. | **CRITICAL** | Passive packet sniffing on campus Wi-Fi allows eavesdroppers to intercept book content and credentials. |
| **THREAT-02: HTTP Digest Auth Flaws** | RFC 2617 Digest Auth uses MD5 hashes. Calibre source code (`auth.py`) explicitly relaxes nonce counter (`nc`) checks to accommodate Firefox bugs. | **HIGH** | Replay attacks and session manipulation are theoretically possible on unencrypted LAN connections. |
| **THREAT-03: Direct Port 8080 Bypass** | If port 8080 remains bound to `::` (all interfaces), users can bypass the institutional landing page and access Calibre directly. | **HIGH** | Circumvents institutional terms of service, custom access logs, and user branding. |
| **THREAT-04: Database Locking & Corruption** | External scripts attempting to write directly to `metadata.db` while Calibre Desktop is open. | **HIGH** | SQLite concurrency conflict (`database is locked`) leading to corruption or desynchronization with Calibre's memory cache. |
| **THREAT-05: Android Cookie Sniffing** | Calibre uses a cleartext cookie (`android_workaround`) for book downloads, expiring in 3600 seconds. | **MEDIUM** | Network attackers can capture this cookie and download restricted library volumes for up to one hour. |
| **THREAT-06: Brute Force Attacks** | Default Calibre configuration has brute-force banning disabled (`ban_for = 0`). | **MEDIUM** | Attackers on the LAN can execute automated credential-stuffing dictionaries against user accounts. |

---

## 2. Required Security Controls & Mitigation Architecture

### 2.1 Network & Transport Layer Controls
1. **Loopback Isolation:**
   - Reconfigure Calibre Content Server to listen exclusively on `127.0.0.1` (`--listen-on 127.0.0.1`).
   - This prevents any remote LAN/Wi-Fi device from contacting port 8080 directly. All inbound traffic must pass through the institutional gateway.
2. **TLS / HTTPS Termination:**
   - Terminate SSL/TLS on the institutional gateway (WAMP Apache or reverse proxy) using an institutional domain certificate or internal PKI certificate.
   - Enforce automatic HTTP-to-HTTPS redirection (`301 Moved Permanently`).
   - Mitigates cleartext credential interception, cookie theft, and packet sniffing.

### 2.2 Identity & Access Governance
1. **Institutional Authentication Gateway:**
   - Implement an institutional login portal supporting individual user credentials stored in MySQL/PostgreSQL with modern password hashing (Bcrypt or Argon2id).
   - Issue encrypted, HttpOnly, SameSite=Lax session cookies.
2. **Upstream Credential Bridging:**
   - Configure Calibre with `--auth-mode basic` and define trusted gateway IPs (`--trusted-ips 127.0.0.1`).
   - The gateway validates student/faculty sessions before proxying requests to Calibre with service authentication headers.
3. **Rate Limiting & Account Protection:**
   - Implement gateway-level rate limiting (maximum 5 failed login attempts per minute per IP).
   - Activate IP lockout and progressive delays to prevent brute-force attacks.

### 2.3 Data Integrity & Concurrency Boundaries
1. **Strict Read-Only Data Boundary:**
   - No external application, script, or web service shall write to `C:\Users\USER\Calibre Library\metadata.db` directly.
   - All catalog queries must use:
     - The authenticated HTTP REST API (`/ajax/...`), or
     - The official CLI interface (`calibredb.exe`), which manages transactional file locks safely.
2. **Audit Logging & Activity Tracking:**
   - Log all patron authentication attempts, downloads, and search queries at the gateway layer.
   - Maintain security audit trails with client IP, timestamp, user ID, and requested resource identifier.
