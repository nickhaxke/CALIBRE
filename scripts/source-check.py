"""Run Calibre's setup commands with the installed Windows dependency runtime.

setup normally assumes an independent Python development environment. Preserve
the installed native extensions and worker launcher when using calibre-debug.
"""
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1] / 'upstream/calibre'
if not os.environ.get('CALIBRE_DEVELOP_FROM'):
    os.environ['CALIBRE_DEVELOP_FROM'] = str(ROOT / 'src')
    if hasattr(sys, 'frozen') or 'calibre' in sys.executable.lower():
        # Re-exec under calibre-debug with CALIBRE_DEVELOP_FROM
        import subprocess
        res = subprocess.run([sys.executable, '-e', str(Path(__file__).resolve())] + sys.argv[1:])
        sys.exit(res.returncode)

native_extensions = getattr(sys, 'extensions_location', None)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
import setup
if native_extensions:
    sys.extensions_location = native_extensions
if hasattr(sys, 'running_from_setup'):
    del sys.running_from_setup
from calibre.utils.config import JSONConfig
JSONConfig('gui')['migrated_forms_to_qt6'] = True

if len(sys.argv) <= 1 or sys.argv[1] == 'institutional':
    import unittest
    import calibre
    src_dir = str(ROOT / 'src' / 'calibre')
    if src_dir not in calibre.__path__:
        calibre.__path__.insert(0, src_dir)
    import calibre.srv.tests.institutional as inst_test
    suite = unittest.defaultTestLoader.loadTestsFromModule(inst_test)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)

sys.argv = [str(ROOT / 'setup.py'), *sys.argv[1:]]
runpy.run_path(str(ROOT / 'setup.py'), run_name='__main__')

