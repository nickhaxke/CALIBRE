import os
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\dev\calibre-institutional")
TEST_INSTALL_DIR = ROOT / "test-environment" / "installed-app"
SRC_DIR = TEST_INSTALL_DIR / "src"
EVIDENCE_DIR = ROOT / "docs" / "evidence"
ARTIFACTS_DIR = Path(r"C:\Users\USER\.gemini\antigravity-ide\brain\3bf4f390-6975-4763-abfe-bfb43d0dc9b4")

sys.path.insert(0, str(SRC_DIR))

from qt.core import QApplication, QTimer, QUrl, QSize
from qt.webengine import QWebEngineView, QWebEngineProfile

app = QApplication.instance() or QApplication([])

view = QWebEngineView()
view.resize(1280, 850)
view.show()

step = 0

def on_load_finished(ok):
    global step
    url = view.url().toString()
    print(f"Loaded: {url} (step={step}, ok={ok})")
    
    if step == 0:
        # Step 0: Landing page loaded, perform login
        print("Submitting login...")
        js_login = """
        (async () => {
            const resp = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username: 'admin', password: 'InstitutionalAdmin2026!'})
            });
            const data = await resp.json();
            return data.success;
        })();
        """
        def login_callback(res):
            print("Login success:", res)
            global step
            step = 1
            # Navigate to catalogue
            QTimer.singleShot(1000, lambda: view.load(QUrl("http://127.0.0.1:8085/calibre/institutional")))
        
        view.page().runJavaScript(js_login, login_callback)
        
    elif step == 1:
        # Step 1: Catalogue page loaded
        print("Capturing catalogue...")
        def capture_cat():
            cat_png = EVIDENCE_DIR / "screenshot_catalogue_page.png"
            view.grab().save(str(cat_png))
            print(f"Captured catalogue: {cat_png}")
            global step
            step = 2
            # Navigate to admin
            view.load(QUrl("http://127.0.0.1:8085/admin"))
        QTimer.singleShot(1500, capture_cat)
        
    elif step == 2:
        # Step 2: Admin page loaded
        print("Capturing admin...")
        def capture_admin():
            admin_png = EVIDENCE_DIR / "screenshot_admin_console.png"
            view.grab().save(str(admin_png))
            print(f"Captured admin console: {admin_png}")
            app.quit()
        QTimer.singleShot(1500, capture_admin)

view.loadFinished.connect(on_load_finished)
view.load(QUrl("http://127.0.0.1:8085/"))

app.exec()
print("Web capture completed.")
