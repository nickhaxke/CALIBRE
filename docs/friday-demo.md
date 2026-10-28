# Friday demonstration — 30 October 2026

Implementation and verification completed locally on 28 October 2026.

## Verdict

**READY for a local demonstration using the sample library.** Physical LAN/Wi-Fi
testing and production installer qualification remain unverified. Both web
listeners are bound to 127.0.0.1; no public deployment or firewall changes were made.

## Architecture and preserved work

The landing page and account/session gateway are the existing institutional
components. The new catalogue, search, category and metadata endpoints run inside
Calibre itself (`calibre.srv.institutional`) and use Calibre's database APIs,
library broker and account restrictions. Reading uses Calibre's existing reader.
The desktop has an optional institutional window title and status-bar label/color.
All existing native toolbar actions remain available.

The source repository is on `institutional/friday-demo`, commit
`c335da40feba3fbd699fd2d3f4d34387cac84c8d`. Its `master` remains at
`77d09457ac0daaf0e0794897a64a3d018f283afd`. The parent project has its own
`institutional-demo` Git branch and a pre-sprint baseline commit. Nothing was pushed.

Existing institutional source/configuration was also backed up to
`C:\dev\calibre-institutional\.local-backups\before-friday-sprint-20261028.zip`.
Existing test-environment data and the ordinary user library were not used for writes.
The sample libraries were copied into `.demo/` before development testing.

## Launch

```powershell
cd C:\dev\calibre-institutional
.\scripts\start-demo.ps1 -Desktop
```

The script uses `C:\Program Files\Calibre2`; set `CALIBRE_BIN_DIR` before launching
if the installed runtime is elsewhere. A first source-server launch compiles the
native web bundle and can take about one minute. The launcher waits for readiness.
Repeating the launcher verifies the existing demo rather than starting duplicate servers.

Open `http://127.0.0.1:8085/`. Use the reader account from
`C:\dev\calibre-institutional\.demo\credentials.json`. Passwords are generated
locally and are excluded from Git. Do not use client or production credentials.

```powershell
.\scripts\stop-demo.ps1
```

This authenticates to the demo administration endpoint, shuts down the gateway,
and stops its owned backend process. It leaves the desktop open. No system-wide
process-name termination is used by the new demo controls.

For an interactive desktop alone:

```powershell
$env:CALIBRE_DEVELOP_FROM = 'C:\dev\calibre-institutional\upstream\calibre\src'
$env:CALIBRE_CONFIG_DIRECTORY = 'C:\dev\calibre-institutional\.demo\desktop-config'
& 'C:\Program Files\Calibre2\calibre-debug.exe' -e C:\dev\calibre-institutional\scripts\demo.py -- desktop
```

The launcher sets an opt-in institutional instance name, so its source desktop's
single-instance lock and IPC pipe are separate from ordinary Calibre.

## Demonstration workflow

1. Open the source desktop and its `.demo\library` collection.
2. Use Add books to import an original sample EPUB. An import fixture generator
   is supplied in `scripts/create_demo_book.py`.
3. Open the landing page, sign in, and search for the new title.
4. Browse real Subjects, Authors, Series or Publishers; switch collections.
5. Open book details and select Read online. The native Calibre reader opens.
6. Sign out and confirm that direct catalogue/cover/book requests are rejected.

The automated desktop integration harness ran inside the real Qt event loop and
called Calibre's existing Add Books action. It imported **The Open Horizon:
Friday Research Edition**, book ID 12, from an original generated EPUB. Its
recorded before-ID set did not contain ID 12; the browser subsequently found the
same book and read its chapter text. This was not a direct SQLite insertion or a
mocked import. A later timer callback recorded that the book already existed;
the before/after evidence is retained to distinguish that callback from the import.

## Configuration

Edit `customization/configuration/demo-branding.json` for the institution name,
abbreviation, motto, logo URL and primary color. This is the demo's presentation
configuration for both the source view and desktop; re-open the desktop after
changing it. The landing logo is a local SVG. No external fonts/images are required.

Runtime server configuration is generated under `.demo/gateway.json`. Both the
desktop and backend use `.demo/library`; the secondary collection is
`.demo/research_archive`. Library management and metadata remain Calibre's own.

The legacy admin database and the demo branding JSON are distinct configuration
surfaces. For this sprint, use the JSON for branding; unifying all administrative
branding edits with source presentation is remaining work.

## Verification evidence

Evidence directory: `C:\dev\calibre-institutional\.demo\evidence`.

- `browser-verification.json`: **17 browser/integration checks passed**, no page errors.
- `desktop-verification.json`: real Qt window, sample library, native action list,
  source module path, imported book ID and before-ID evidence.
- `desktop-source.png`: branded desktop and imported book.
- `landing-desktop.png`, `login.png`, `library-desktop.png`, `book-details.png`.
- `native-reader.png`: visible chapter text in the native reader.
- `landing-mobile.png`, `library-mobile.png`: 390px responsive layouts.
- `.demo/source-proof.txt`: runtime imports resolved to the checked-out source.
- `.demo/desktop-import-events.jsonl`: native Add Books request and before-ID set.

The browser checks cover branding, login, cookie flags, actual covers and metadata,
desktop-to-web discovery, author/tag search, categories, multi-library URLs,
details, EPUB reading, mobile overflow, disabled maintenance routes, exact-origin
CSRF validation, 32 concurrent cover requests, inert malicious metadata rendering,
logout revocation, and administrator settings/library-table navigation.

Eight isolated gateway regression tests passed:

```powershell
& 'C:\Program Files\Calibre2\calibre-debug.exe' -e C:\dev\calibre-institutional\tests\test_friday_demo.py -- -v
```

Two Calibre source tests passed using its setup test command through the installed
Windows runtime adapter:

```powershell
$env:CALIBRE_DEVELOP_FROM = 'C:\dev\calibre-institutional\upstream\calibre\src'
$env:CALIBRE_CONFIG_DIRECTORY = 'C:\dev\calibre-institutional\.demo\test-config'
& 'C:\Program Files\Calibre2\calibre-debug.exe' -e C:\dev\calibre-institutional\scripts\source-check.py -- test --test-module=srv --test-name=institutional_authentication_and_restrictions --test-name=institutional_pagination_and_asset_boundaries
```

These tests verify real server authentication, per-library book restrictions,
prefix-safe content URLs, pagination and asset boundaries using temporary libraries.

The native RapydScript build passed (98 seconds). Python syntax checks passed for
12 gateway/launcher/test files; four JavaScript files passed Node syntax checks.

Browser verification uses the existing development Playwright runtime:

```powershell
$env:NODE_PATH = 'C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
node C:\dev\calibre-institutional\scripts\verify-demo.cjs
```

The ordinary desktop automation helper failed to initialize with a kernel-assets
path error. Desktop verification therefore used the in-application Qt harness;
browser verification used headless Microsoft Edge with Playwright.

## Security and reliability changes

- Loopback-only default listeners and explicit allowed origins.
- Backend address taken from configuration; no hardcoded proxy target.
- Backend startup must succeed before the gateway starts listening.
- Owned-process shutdown; no adoption or termination of an unrelated backend.
- No automatic fallback to development libraries or seeded privileged accounts.
- Setup-maintenance routes disabled; post-setup information requires administrator access.
- Forwarding headers accepted only from explicitly configured trusted proxies.
- Exact origin validation; no permissive referer-prefix or loopback CSRF bypass.
- User account changes revoke old gateway sessions.
- Text/DOM rendering for catalogue and administrative metadata.
- Correct admin field mappings, profile handler, and hidden-modal behavior.
- SQLite configuration scopes release file handles on Windows.
- Gateway connection backlog increased to handle parallel cover requests.

## Remaining work and limits

- Native C++ build failed: Visual C++ `vcvarsall.bat` is unavailable. The demo uses
  the matching installed Calibre 9.17.0 native extensions, as supported by the
  [Windows source development workflow](https://manual.calibre-ebook.com/develop.html#windows-development-environment).
- Upstream lint/type-check commands were attempted but blocked because `uv` is
  unavailable. No dependency installations were performed.
- The entire upstream and legacy 57-test institutional suites were not run.
- No physical mobile device/LAN/Wi-Fi run, TLS deployment, public exposure,
  load/capacity certification, or production-data migration was performed.
- The native reader engine is preserved; full annotation/editing/conversion
  regression coverage remains outstanding.
- Existing fixture books with missing publisher/year metadata retain those gaps.
- The installer in `dist/` is an old artifact and does not contain this sprint.
  Production installer, service packaging, clean install, upgrades, and client
  deployment remain P2 work.

Full changed-file paths are recorded in `docs/friday-demo-files.json`.
