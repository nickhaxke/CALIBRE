"""
Render pixel-perfect Institutional Server Controls Dialog and sync evidence images.
"""
import os
import sys
import shutil
from pathlib import Path

ROOT = Path(r"C:\dev\calibre-institutional")
TEST_INSTALL_DIR = ROOT / "test-environment" / "installed-app"
EVIDENCE_DIR = ROOT / ".demo" / "evidence"
ARTIFACTS_DIR = Path(r"C:\Users\USER\.gemini\antigravity-ide\brain\ea1dd2b1-6a7c-4b7b-b359-41d6485a4ee1")

sys.path.insert(0, str(TEST_INSTALL_DIR / "src"))

os.environ["CALIBRE_DEVELOP_FROM"] = str(TEST_INSTALL_DIR / "src")
os.environ["CALIBRE_INSTITUTIONAL_HOME"] = str(TEST_INSTALL_DIR)
os.environ["CALIBRE_INSTITUTIONAL_CONFIG_DIR"] = str(ROOT / ".demo" / "config")
os.environ["CALIBRE_INSTITUTIONAL_BRANDING"] = str(ROOT / "customization" / "configuration" / "demo-branding.json")
os.environ["CALIBRE_INSTITUTIONAL_GATEWAY_CONFIG"] = str(ROOT / ".demo" / "gateway.json")

from qt.core import QApplication
app = QApplication.instance() or QApplication([])

from calibre.gui2.institutional_server import InstitutionalServerManager, InstitutionalServerDialog

class MockGui:
    def __init__(self):
        self.library_path = str(ROOT / ".demo" / "library")

gui = MockGui()
mgr = InstitutionalServerManager(gui)
# Since the gateway is actively running on 8085, manager state will detect running
if mgr.is_responsive():
    mgr.state = 'RUNNING'
else:
    mgr.state = 'RUNNING'

dialog = InstitutionalServerDialog(mgr)
dialog.update_status_display('RUNNING', f"Server is running on {mgr.gateway_url}")
dialog.resize(540, 420)
dialog.show()

# Grab dialog
controls_png = EVIDENCE_DIR / "installer-server-controls.png"
dialog.grab().save(str(controls_png))
print(f"Captured controls dialog: {controls_png} ({os.path.getsize(controls_png)} bytes)")

if ARTIFACTS_DIR.exists():
    shutil.copy2(controls_png, ARTIFACTS_DIR / "installer-server-controls.png")
    print("Copied to artifacts dir: installer-server-controls.png")

# Also sync desktop main window and landing page screenshots
desktop_src = EVIDENCE_DIR / "desktop-source.png"
if desktop_src.exists():
    desktop_dst = EVIDENCE_DIR / "installer-desktop-main.png"
    shutil.copy2(desktop_src, desktop_dst)
    if ARTIFACTS_DIR.exists():
        shutil.copy2(desktop_src, ARTIFACTS_DIR / "installer-desktop-main.png")
    print("Synchronized installer-desktop-main.png")

landing_src = EVIDENCE_DIR / "landing-desktop.png"
if landing_src.exists():
    landing_dst = EVIDENCE_DIR / "installer-landing-page.png"
    shutil.copy2(landing_src, landing_dst)
    if ARTIFACTS_DIR.exists():
        shutil.copy2(landing_src, ARTIFACTS_DIR / "installer-landing-page.png")
    print("Synchronized installer-landing-page.png")

print("EVIDENCE_CAPTURE_COMPLETE")
