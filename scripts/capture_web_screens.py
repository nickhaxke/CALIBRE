import os
import sys
import json
import shutil
import urllib.request
import subprocess
from pathlib import Path

ROOT = Path(r"C:\dev\calibre-institutional")
EVIDENCE_DIR = ROOT / "docs" / "evidence"
ARTIFACTS_DIR = Path(r"C:\Users\USER\.gemini\antigravity-ide\brain\3bf4f390-6975-4763-abfe-bfb43d0dc9b4")
msedge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

# 1. Login
login_data = json.dumps({"username": "admin", "password": "InstitutionalAdmin2026!"}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8085/api/auth/login",
    data=login_data,
    headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8085"}
)
login_resp = json.loads(opener.open(req).read().decode())
print("Logged in as:", login_resp.get("user"))

# 2. Fetch Catalogue HTML
cat_resp = opener.open("http://127.0.0.1:8085/calibre/institutional").read().decode("utf-8")
# Fix relative assets to load through gateway port 8085
cat_html = cat_resp.replace('<head>', '<head><base href="http://127.0.0.1:8085/calibre/">')
cat_file = EVIDENCE_DIR / "temp_catalogue.html"
cat_file.write_text(cat_html, encoding="utf-8")

cat_png = EVIDENCE_DIR / "screenshot_catalogue_page.png"
subprocess.run([
    msedge,
    "--headless",
    "--disable-gpu",
    "--hide-scrollbars",
    "--window-size=1280,820",
    f"--screenshot={cat_png}",
    str(cat_file.resolve().as_uri())
], capture_output=True)
print(f"Captured Catalogue Page: {cat_png} ({cat_png.stat().st_size} bytes)")

# 3. Fetch Admin Console HTML
admin_resp = opener.open("http://127.0.0.1:8085/admin").read().decode("utf-8")
admin_html = admin_resp.replace('<head>', '<head><base href="http://127.0.0.1:8085/">')
admin_file = EVIDENCE_DIR / "temp_admin.html"
admin_file.write_text(admin_html, encoding="utf-8")

admin_png = EVIDENCE_DIR / "screenshot_admin_console.png"
subprocess.run([
    msedge,
    "--headless",
    "--disable-gpu",
    "--hide-scrollbars",
    "--window-size=1280,850",
    f"--screenshot={admin_png}",
    str(admin_file.resolve().as_uri())
], capture_output=True)
print(f"Captured Admin Console: {admin_png} ({admin_png.stat().st_size} bytes)")

# 4. Clean up temp HTML
cat_file.unlink(missing_ok=True)
admin_file.unlink(missing_ok=True)

# 5. Sync all screenshots to artifact directory
for p in EVIDENCE_DIR.glob("*.png"):
    dst = ARTIFACTS_DIR / p.name
    shutil.copy2(p, dst)
    print(f"Synced {p.name} to {dst}")

print("All screenshots successfully captured and synchronized.")
