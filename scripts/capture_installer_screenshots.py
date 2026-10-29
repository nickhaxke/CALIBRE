"""
Captures high-resolution screenshots of the installed customized Calibre Desktop,
the Start Server controls dialog, and the landing page for verification evidence.
"""

import os
import sys
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / '.demo'
EVIDENCE = DEMO / 'evidence'
EVIDENCE.mkdir(parents=True, exist_ok=True)

ARTIFACTS_DIR = Path(r"C:\Users\USER\.gemini\antigravity-ide\brain\ea1dd2b1-6a7c-4b7b-b359-41d6485a4ee1")

CAPTURE_CONFIG = ROOT / 'test-environment' / 'capture-config'
CAPTURE_CONFIG.mkdir(parents=True, exist_ok=True)

# Copy base configuration to avoid first-run wizard prompting
for json_file in (DEMO / 'desktop-config').glob('*.json'):
    shutil.copy2(json_file, CAPTURE_CONFIG / json_file.name)

os.environ['CALIBRE_CONFIG_DIRECTORY'] = str(CAPTURE_CONFIG)
os.environ['CALIBRE_INSTITUTIONAL_INSTANCE'] = 'capture-instance'
os.environ['CALIBRE_NO_SI_DANGER_DANGER'] = '1'

from qt.core import QTimer
from calibre.gui2.ui import Main
from calibre.gui2.main import main

original_title = Main.set_window_title

def capture_workflow(gui):
    try:
        gui.resize(1280, 800)
        
        # 1. Capture Desktop Window
        desktop_shot = EVIDENCE / "installer-desktop-main.png"
        gui.grab().save(str(desktop_shot))
        print(f"SAVED_DESKTOP_SCREENSHOT: {desktop_shot}")
        if ARTIFACTS_DIR.exists():
            shutil.copy2(desktop_shot, ARTIFACTS_DIR / "installer-desktop-main.png")

        # 2. Open and capture Institutional Server Controls Dialog
        if 'Institutional Server' in gui.iactions:
            gui.iactions['Institutional Server'].show_server_dialog()
            dialog = gui.iactions['Institutional Server'].dialog
            if dialog:
                dialog.resize(520, 480)
                def capture_dialog():
                    dlg_shot = EVIDENCE / "installer-server-controls.png"
                    dialog.grab().save(str(dlg_shot))
                    print(f"SAVED_CONTROLS_SCREENSHOT: {dlg_shot}")
                    if ARTIFACTS_DIR.exists():
                        shutil.copy2(dlg_shot, ARTIFACTS_DIR / "installer-server-controls.png")
                    dialog.close()
                    QTimer.singleShot(500, gui.quit)
                QTimer.singleShot(1000, capture_dialog)
                return
    except Exception as e:
        print(f"Error capturing screenshot: {e}")
    QTimer.singleShot(500, gui.quit)

def title_hook(gui):
    original_title(gui)
    if not getattr(gui, '_capture_scheduled', False):
        gui._capture_scheduled = True
        QTimer.singleShot(2500, lambda: capture_workflow(gui))

Main.set_window_title = title_hook

if __name__ == '__main__':
    main(['calibre', '--with-library=' + str(DEMO / 'library'), '--ignore-plugins'])
