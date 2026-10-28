# Source Code Architecture Map
**Project:** Calibre Institutional Customization  
**Phase:** Phase 0 — Source Acquisition & Architecture Discovery  
**Upstream Repository:** `https://github.com/kovidgoyal/calibre.git`  
**Upstream Branch:** `master`  
**Commit SHA:** `77d09457ac0daaf0e0794897a64a3d018f283afd`  
**Upstream Version:** `9.17.0` (numeric: `(9, 17, 0)`)  
**Installed Version:** `9.17.0` (100% Binary/Source Compatibility Verified)  

---

## 1. Top-Level Codebase Organization

The Calibre source repository is structured into distinct functional domains:

```
upstream/calibre/
├── bypy/                   # Build system for standalone cross-platform bundles (QEMU VMs)
├── resources/              # Runtime static assets, images, icons, and templates
│   ├── content-server/     # Web server HTML/CSS templates and generated client bundles
│   └── images/             # Desktop GUI and web icons (SVG, PNG, ICO)
├── setup/                  # Installer generation and extension build scripts
├── src/
│   ├── calibre/            # Core Python package
│   │   ├── db/             # Database access, caching, search, and storage abstractions
│   │   ├── gui2/           # Desktop Qt6 Graphical User Interface
│   │   ├── srv/            # High-performance asynchronous Content Server
│   │   ├── utils/          # Platform helpers, IPC, resources, and rapydscript compiler
│   │   ├── constants.py    # Application metadata, version, and environment flags
│   │   └── linux.py        # Central CLI and GUI executable entry points specification
│   └── pyj/                # RapydScript (Python-to-JS) source code for Content Server SPA
```

---

## 2. Desktop Application Architecture

### 2.1 Entry Points
- **Specification:** `src/calibre/linux.py` defines the `entry_points` map used by installer scripts to generate Windows executables:
  - `calibre` -> `calibre.gui_launch:calibre`
  - `calibre-server` -> `calibre.srv.standalone:main`
  - `calibredb` -> `calibre.db.cli.main:main`
  - `calibre-debug` -> `calibre.debug:main`
  - `ebook-viewer` -> `calibre.gui_launch:ebook_viewer`
  - `ebook-edit` -> `calibre.gui_launch:ebook_edit`
- **Launcher Execution:** `src/calibre/gui_launch.py` implements the detachment logic (`do_detach`) and suppressive Qt logging filters before importing GUI libraries.
- **Application Startup:** `src/calibre/gui2/main.py:main()` initializes Qt application context (`init_qt`), enforces single-instance mutual exclusion (`SingleInstance`), and launches the main window (`run_main -> run_gui`).

### 2.2 Desktop GUI Implementation
- **Main Window Controller:** `src/calibre/gui2/ui.py:Main`
  - Implements the complete librarian interface, book table view, tag browser, and cover grid.
  - Window Title: Controlled dynamically in `src/calibre/gui2/ui.py:Main.library_moved`:
    ```python
    title = '{} — || {}{} ||'.format(__appname__, self.iactions['Choose Library'].library_name(), restrictions)
    self.setWindowTitle(title)
    ```
  - Application Icon: Initialized in `src/calibre/gui2/ui.py` via `self.setWindowIcon(qapplication_or_fail().windowIcon())`.
- **Branding & Metadata:**
  - `src/calibre/constants.py`: Defines `__appname__ = 'calibre'`, `numeric_version = (9, 17, 0)`, and `__version__ = '9.17.0'`.
  - `resources/images/`: Contains core SVG and PNG icons: `calibre.svg`, `bookshelf.png`, `lt.png` (app logo), `catalog.png`.
- **Book-Management Workflows:**
  - Book Import: `src/calibre/gui2/add.py` (Add books, directory scanning, format detection).
  - Metadata Editing: `src/calibre/gui2/metadata/single.py` and `bulk.py` (Custom tags, identifiers, series).
  - Format Conversion: `src/calibre/gui2/convert/` and `src/calibre/ebooks/conversion/plumber.py`.
- **Configuration Engine:**
  - Backed by JSON dictionaries in `%APPDATA%\calibre\`: `gui.json` (window layout, stats) and `global.py.json` (library paths, default formats).
  - Implemented in `src/calibre/utils/config.py` (`JSONConfig`, `ConfigInterface`).

---

## 3. Content Server Architecture

### 3.1 HTTP Server Core
- **Server Loop:** `src/calibre/srv/loop.py:ServerLoop`
  - Custom asynchronous event loop based on Python `selectors`, managing multi-threaded socket pools, keep-alive connections, and zero-copy `sendfile` transfers.
- **Embedded vs Standalone Mode:**
  - **Embedded Mode (Active on client machine):** `src/calibre/srv/embedded.py:EmbeddedServer`. Spawned as a background thread inside `calibre.exe` when the desktop user enables Content Server.
  - **Standalone Mode:** `src/calibre/srv/standalone.py:main()`. Headless console executable (`calibre-server.exe`) capable of running as a system service.
- **Request Dispatcher:** `src/calibre/srv/handler.py:HttpHandler` and `src/calibre/srv/routes.py:Router`.
  - Endpoints register via the `@endpoint(path, methods, auth_required)` decorator.

### 3.2 Endpoints & Route Definitions
- **Root Endpoint:** `src/calibre/srv/code.py:index`
  - Decorator: `@endpoint('', auth_required=False)`
  - Action: Returns `resources/content-server/index-generated.html` (the bundled SPA shell). Because `auth_required=False`, initial GET `/` returns HTTP 200 without authentication.
- **Data Initialization:** `src/calibre/srv/code.py:init`
  - Decorator: `@endpoint('/interface-data/init', postprocess=json)`
  - Requires authentication when server auth is enabled (`auth=True`). Returns HTTP 401 Unauthorized if no credentials are supplied.
- **Content & File Serving:** `src/calibre/srv/content.py`
  - Static resources: `@endpoint('/static/{+what}', auth_required=False)`
  - Book download: `@endpoint('/get/{what}/{book_id}/{library_id=None}', android_workaround=True)`
- **AJAX API:** `src/calibre/srv/ajax.py`
  - `/ajax/books/{library_id}`: Paginated book list and metadata.
  - `/ajax/categories/{library_id}`: Authors, series, tags, publishers hierarchy.
  - `/ajax/search/{library_id}`: Full-text and metadata search queries.
  - `/ajax/library-info`: Active library names and UUIDs.

### 3.3 Authentication & Authorization Mechanisms
- **Authentication Controller:** `src/calibre/srv/auth.py:AuthController`
  - Implements **RFC 2617 HTTP Digest Authentication** by default (`WWW-Authenticate: Digest realm="calibre", nonce="...", algorithm="MD5", qop="auth"`).
  - Secret & Nonce Generation: `synthesize_nonce(key_order, realm, secret)` generates timestamp-signed nonces to prevent replay attacks (`validate_nonce`).
  - Stale Nonce Handling: `is_nonce_stale` invalidates nonces after `MAX_AGE_SECONDS = 3600`.
  - Android Workaround: Cookie-based download authentication (`ANDROID_COOKIE = 'android_workaround'`) allowing background downloaders to bypass HTTP Auth.
  - Basic Auth Option: Configured via `auth_mode = 'basic'`, recommended when running behind an SSL-terminating reverse proxy.
  - IP Brute Force Mitigation: `src/calibre/srv/auth.py:BanList` temporarily bans IPs after `ban_after` failed attempts for `ban_for` minutes.
- **User Database:** `src/calibre/srv/users.py:UserManager`
  - Backed by an SQLite database (`%APPDATA%\calibre\server-users.sqlite`).
  - Passwords stored as SHA-256 / PBKDF2 hashes.
  - Managed via CLI: `calibre-server --manage-users` (`src/calibre/srv/manage_users_cli.py`).

### 3.4 Browser Interface (Frontend SPA)
- **RapydScript Implementation:** The client interface is **not** written in standard JavaScript, Vue, or React. It is written in **RapydScript** (Pythonic syntax compiled to JavaScript), located in `src/pyj/`:
  - `src/pyj/srv.pyj`: Main entry point initializing routing and session state.
  - `src/pyj/book_list/`: UI views including cover grid (`cover_grid.pyj`), book details (`book_details.pyj`), search (`fts.pyj`), and virtual libraries.
  - `src/pyj/read_book/`: Complete in-browser eBook reader (EPUB, PDF rendering, annotations, highlights).
- **Compilation Toolchain:** `src/calibre/utils/rapydscript.py:compile_srv` compiles `src/pyj/srv.pyj` into `resources/content-server/index-generated.html` using an embedded Node-free JS compiler (`rapydscript/compiler.js.xz`).

---

## 4. Data Layer Architecture

### 4.1 Calibre Library Structure
A Calibre library is a dedicated filesystem directory containing:
1. `metadata.db`: SQLite 3 database storing metadata, tags, authors, publishers, custom columns, and book-to-file mappings.
2. Directory Hierarchy: Formatted strictly as:
   ```
   <Author_Name>/
   └── <Book_Title> (<book_id>)/
       ├── cover.jpg
       ├── metadata.opf
       ├── book.epub
       └── book.pdf
   ```
3. Special Directories: `.calibre_notes/` (HTML rich text field notes) and `.calibre_trash/` (soft-deleted items).

### 4.2 Database Access & Concurrency Model
- **Database Engine:** `src/calibre/db/backend.py:DB`
  - Interfaces with SQLite via `apsw` (Another Python SQLite Wrapper) using custom C extensions (`sqlite_extension.cpp`).
  - Registers ICU custom sorting collations (`calibre_title_sort`, `calibre_author_sort`, `numerical`).
- **In-Memory Cache:** `src/calibre/db/cache.py:Cache`
  - Calibre loads all book metadata into memory for sub-millisecond search and sorting performance.
  - **Critical Concurrency Boundary:** Direct external writes to `metadata.db` while Calibre Desktop is running will bypass this cache, resulting in database lock errors (`database is locked`) or catastrophic cache desynchronization.
- **Safe Integration Boundaries:**
  - **REST API:** Querying Calibre Content Server endpoints (`/ajax/books`, `/ajax/search`).
  - **CLI Tools:** Executing `calibredb` commands (`calibredb list`, `calibredb show_metadata`), which properly acquire inter-process locks.

---

## 5. Configuration & Extension Points

- **Reverse Proxy Support:** Configured in `src/calibre/srv/opts.py`:
  - `url_prefix`: Allows prepending a prefix (e.g. `/library` or `/calibre`) to all internal URLs.
  - `auth_mode`: Setting to `'basic'` enables standard `Authorization: Basic ...` headers, enabling reverse proxy authentication injection.
  - `listen_on`: Binds the server to `127.0.0.1` so that only the local reverse proxy can reach it.
  - `trusted_ips`: Allows bypassing authentication or write locks for internal gateway IPs.
- **Packaging System:** `setup/installers.py` and `bypy/`
  - Calibre uses `bypy` (VM-driven build tool) running on Linux with QEMU Windows guests to compile all dependencies (Qt, Python, OpenSSL, PoDoFo) from source.
  - Creating a standalone installer from source on Windows requires a full Linux build host or using an installer wrapper (e.g., Inno Setup) around the binary distribution.
