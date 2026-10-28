"""Qt integration harness: launch real Calibre and import through its Add Books action.

The timer runs inside the application's event loop. It does not write metadata.db
directly, simulate an import, or touch the user's ordinary Calibre profile.
"""
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / '.demo'
if Path(os.environ.get('CALIBRE_CONFIG_DIRECTORY', '')).resolve() != (DEMO / 'desktop-config').resolve():
    raise SystemExit('Refusing to launch the verification harness outside its dedicated profile.')
sys.path.insert(0, str(ROOT / 'scripts'))
from create_demo_book import TITLE, create_book
from qt.core import QTimer
from calibre.gui2.ui import Main
from calibre.gui2.main import main

EVIDENCE = DEMO / 'evidence'
EVIDENCE.mkdir(exist_ok=True)
original_title = Main.set_window_title


def save_result(result):
    (DEMO / 'desktop-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


def start_verification(gui):
    try:
        if Path(gui.current_db.library_path).resolve() != (DEMO / 'library').resolve():
            raise RuntimeError('Desktop opened a different library; no import attempted.')
        gui.resize(1280, 820)
        path = create_book(DEMO / 'ingest/open-horizon.epub')
        already_present = gui.current_db.new_api.search('title:"=' + TITLE + '"')
        if not already_present:
            with open(DEMO / 'desktop-import-events.jsonl', 'a', encoding='utf-8') as events:
                events.write(json.dumps({'action': 'desktop_add_books_requested', 'title': TITLE, 'library': gui.current_db.library_path, 'before_ids': sorted(gui.current_db.new_api.all_book_ids())}) + '\n')
            gui.iactions['Add Books'].add_filesystem_book([str(path)], allow_device=False)
        attempts = [0]

        def verify():
            attempts[0] += 1
            ids = gui.current_db.new_api.search('title:"=' + TITLE + '"')
            if not ids and attempts[0] < 90:
                QTimer.singleShot(1000, verify)
                return
            if not ids:
                save_result({'passed': False, 'error': 'Desktop import timed out'})
                return
            gui.search.set_search_string('title:"=' + TITLE + '"')

            def capture():
                screenshot = EVIDENCE / 'desktop-source.png'
                captured = gui.grab().save(str(screenshot))
                save_result({'passed': True, 'import_method': 'Calibre Desktop Add Books action', 'already_present': bool(already_present), 'title': TITLE, 'book_ids': sorted(ids), 'library': gui.current_db.library_path, 'window_title': gui.windowTitle(), 'source_module': sys.modules['calibre.gui2.ui'].__file__, 'screenshot': str(screenshot), 'screenshot_saved': captured, 'native_actions_present': all(key in gui.iactions for key in ('Add Books', 'Edit Metadata', 'Convert Books', 'Choose Library'))})
            QTimer.singleShot(2000, capture)
        QTimer.singleShot(1000, verify)
    except Exception:
        save_result({'passed': False, 'error': traceback.format_exc()})


def title_and_schedule(gui):
    original_title(gui)
    if not getattr(gui, '_institutional_verification_scheduled', False):
        gui._institutional_verification_scheduled = True
        QTimer.singleShot(4000, lambda: start_verification(gui))


Main.set_window_title = title_and_schedule
main(['calibre', '--with-library=' + str(DEMO / 'library'), '--ignore-plugins'])
